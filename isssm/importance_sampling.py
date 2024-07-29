# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/40_importance_sampling.ipynb.

# %% auto 0
__all__ = ['v_log_weights', 'log_weights_t', 'log_weights', 'lcssm_importance_sampling', 'normalize_weights', 'ess', 'ess_lw',
           'ess_pct']

# %% ../nbs/40_importance_sampling.ipynb 4
from tensorflow_probability.substrates.jax.distributions import (
    MultivariateNormalFullCovariance as MVN,
    MultivariateNormalDiag as MVN_diag,
)
import jax.numpy as jnp
from jaxtyping import Float, Array
from jax import vmap
from functools import partial
from .typing import PGSSM



def log_weights_t(
    s_t: Float[Array, "p"],  # signal
    y_t: Float[Array, "p"],  # observation
    xi_t: Float[Array, "p"],  # parameters
    dist,  # observation distribution
    z_t: Float[Array, "p"],  # synthetic observation
    Omega_t: Float[Array, "p p"],  # synthetic observation covariance, assumed diagonal
) -> Float:  # single log weight
    """Log weight for a single time point."""
    p_ys = dist(s_t, xi_t).log_prob(y_t).sum()

    #g_zs = MVN(s_t, Omega_t).log_prob(z_t).sum()
    # avoid triangular solve problems
    omega_t = jnp.sqrt(jnp.diag(Omega_t))
    g_zs = MVN_diag(s_t, omega_t).log_prob(z_t).sum()

    return p_ys - g_zs


def log_weights(
    s: Float[Array, "n+1 p"],  # signals
    y: Float[Array, "n+1 p"],  # observations
    dist,  # observation distribution
    xi: Float[Array, "n+1 p"],  # observation parameters
    z: Float[Array, "n+1 p"],  # synthetic observations
    Omega: Float[Array, "n+1 p p"],  # synthetic observation covariances:
) -> Float[Array, "n+1"]:  # log weights
    """Log weights for all time points"""
    p_ys = dist(s, xi).log_prob(y).sum()
    #g_zs = MVN(s, Omega).log_prob(z).sum()
    omega = jnp.sqrt(vmap(jnp.diag)(Omega))
    # avoid triangulra solve problems
    g_zs = MVN_diag(s, omega).log_prob(z).sum()

    return p_ys - g_zs

# %% ../nbs/40_importance_sampling.ipynb 7
from jaxtyping import Float, Array, PRNGKeyArray
from .kalman import FFBS
import jax.random as jrn
from .typing import GLSSM

v_log_weights = vmap(log_weights, (0, None, None, None, None, None))

def lcssm_importance_sampling(
    y: Float[Array, "n+1 p"],  # observations
    model: PGSSM,
    z: Float[Array, "n+1 p"],  # synthetic observations
    Omega: Float[Array, "n+1 p p"],  # covariance of synthetic observations
    N: int,  # number of samples
    key: PRNGKeyArray  # random key
) -> tuple[Float[Array, "N n+1 m"], Float[Array, "N"]]:  # importance samples and weights
    x0, A, Sigma, B, dist, xi = model
    key, subkey = jrn.split(key)

    glssm = GLSSM(x0, A, Sigma, B, Omega)
    samples = FFBS(z, glssm, N, subkey)

    vB = partial(vmap(jnp.matmul), B)

    s = vmap(vB)(samples)

    lw = v_log_weights(s, y, dist, xi, z, Omega)

    return samples, lw

# %% ../nbs/40_importance_sampling.ipynb 12
from jaxtyping import Float, Array


def normalize_weights(
    log_weights: Float[Array, "N"]  # log importance sampling weights
) -> Float[Array, "N"]:  # normalized importance sampling weights
    """Normalize importance sampling weights."""
    max_weight = jnp.max(log_weights)

    log_weights_corrected = log_weights - max_weight

    weights = jnp.exp(log_weights_corrected)

    return weights / weights.sum()

# %% ../nbs/40_importance_sampling.ipynb 15
from jaxtyping import Float, Array


def ess(
    normalized_weights: Float[Array, "N"]  # the normailzed weights
) -> Float:  # the effective sample size
    """Compute the effective sample size of a set of normalized weights"""
    return 1 / (normalized_weights**2).sum()


def ess_lw(
    log_weights: Float[Array, "N"]  # the log weights
) -> Float:  # the effective sample size
    """Compute the effective sample size of a set of log weights"""
    return ess(normalize_weights(log_weights))

# %% ../nbs/40_importance_sampling.ipynb 18
def ess_pct(log_weights):
    N, = log_weights.shape
    return ess_lw(log_weights) / N * 100 
