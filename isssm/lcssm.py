# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/20_lcssm.ipynb.

# %% auto 0
__all__ = ['simulate_lcssm', 'nb_lcssm', 'log_probs_y', 'log_prob']

# %% ../nbs/20_lcssm.ipynb 5
from jaxtyping import Float, Array, PRNGKeyArray
from isssm.glssm import log_probs_x

# %% ../nbs/20_lcssm.ipynb 6
from isssm.glssm import simulate_states
from jax import vmap
import jax.numpy as jnp
import jax.random as jrn
import tensorflow_probability.substrates.jax.distributions as tfd
from jax import lax
MVN = tfd.MultivariateNormalFullCovariance

# matmul with $(A_t)_{t}$ and $(X_t)_{t}$
mm_time = vmap(jnp.matmul, (0, 0))
# matmul with $(A_t)_{t}$ and $(X^i_t)_{i,t}$
mm_time_sim = vmap(mm_time, (None, 0))

# %% ../nbs/20_lcssm.ipynb 7
def simulate_lcssm(
    x0: Float[Array, "m"],  # initial state
    A: Float[Array, "n m m"],  # transition matrices
    Sigma: Float[Array, "n+1 m m"],  # innovation covariances
    B: Float[Array, "n+1 p m"],  # signal matrices
    dist,  # observation distribution
    xi, # observation parameters
    N: int,  # number of samples
    key: PRNGKeyArray,  # random key
) -> tuple[
    Float[Array, "N n+1 m"], Float[Array, "N n+1 p"]
]:  # simulated states and observations
    key, subkey = jrn.split(key)
    X = simulate_states(x0, A, Sigma, N, subkey)
    S = mm_time_sim(B, X)

    Y = dist(S, xi).sample(seed=subkey)

    return X, Y

# %% ../nbs/20_lcssm.ipynb 9
from tensorflow_probability.substrates.jax.distributions import (
    NegativeBinomial as NBinom,
)


def nb_lcssm(
    x0: Float[Array, "m"], # initial state
    A: Float[Array, "n m m"], # transition matrices
    Sigma: Float[Array, "n+1 m m"], # innovation covariances
    B: Float[Array, "n+1 p m"], # signal matrices
    r: Float, # overdispersion parameter
): # negative binomial LCSSM
    """Create a negative binomial LCSSM with constant overdispersion"""

    np1,m, _ = B.shape
    xi = jnp.full((np1, m), r)

    def dist_nb(log_mu, xi):
        mu = jnp.exp(log_mu)
        return NBinom(r, probs=mu / (xi + mu))

    return x0, A, Sigma, B, dist_nb, xi

# %% ../nbs/20_lcssm.ipynb 15
def log_probs_y(
    x: Float[Array, "n+1 m"],  # states
    y: Float[Array, "n+1 p"],  # observations
    B: Float[Array, "n+1 p m"],  # signal matrices
    dist,  # observation distribution
    xi, # observation parameters
):
    s = (B @ x[:,:,None])[:,:,0]
    return dist(s, xi).log_prob(y).sum(axis=1)

def log_prob(
    x: Float[Array, "n+1 m"],  # states
    y: Float[Array, "n+1 p"],  # observations
    x0: Float[Array, "m"],  # initial mean
    A: Float[Array, "n m m"],  # transition matrices
    Sigma: Float[Array, "n+1 m m"],  # innovation covariances
    B: Float[Array, "n+1 p m"],  # signal matrices
    dist,  # observation distribution
    xi, # observation parameters
):
    px = log_probs_x(x, x0, A, Sigma).sum()
    py = log_probs_y(x, y, B, dist, xi).sum()
    return px + py
