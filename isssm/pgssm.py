# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/20_pgssm.ipynb.

# %% auto 0
__all__ = ['simulate_pgssm', 'nb_pgssm_runnning_example', 'log_probs_y', 'log_prob']

# %% ../nbs/20_pgssm.ipynb 5
import jax.numpy as jnp
import jax.random as jrn
from jax import lax, vmap
from jaxtyping import Array, Float, PRNGKeyArray
from tensorflow_probability.substrates.jax.distributions import \
    NegativeBinomial as NBinom
from tensorflow_probability.substrates.jax.distributions import Poisson

from .glssm import log_probs_x, simulate_states
from .typing import PGSSM, GLSSMObservationModel, GLSSMState
from .util import mm_time, mm_time_sim

# %% ../nbs/20_pgssm.ipynb 6
def simulate_pgssm(
    pgssm: PGSSM,
    N: int,  # number of samples
    key: PRNGKeyArray,  # random key
) -> tuple[
    Float[Array, "N n+1 m"], Float[Array, "N n+1 p"]
]:  # simulated states and observations
    x0, A, Sigma, B, dist, xi = pgssm
    key, subkey = jrn.split(key)
    X = simulate_states(GLSSMState(x0, A, Sigma), N, subkey)
    S = mm_time_sim(B, X)

    Y = dist(S, xi).sample(seed=subkey)

    return X, Y

# %% ../nbs/20_pgssm.ipynb 8
from .models.stsm import stsm
from .models.pgssm import nb_pgssm
import jax.scipy.linalg as jsla


def nb_pgssm_runnning_example(
    x0_trend: Float[Array, "m"] = jnp.zeros(2),
    r: Float = 20,
    s2_trend: Float = 0.01,
    s2_speed: Float = 0.1,
    alpha: Float = 0.1,
    omega2: Float = 0.01,
    n: int = 100,
    x0_seasonal: Float[Array, "s"] = jnp.zeros(5),
    s2_seasonal: Float = 0.1,
    Sigma0_seasonal: Float[Array, "s s"] = .1 * jnp.eye(5),
    s_order: int = 5,
) -> PGSSM: # the running example for this package
    """a structural time series model with NBinom observations"""
    Sigma0 = jsla.block_diag(0.01 * jnp.eye(2), Sigma0_seasonal)
    x0 = jnp.concatenate((x0_trend, x0_seasonal))

    model = nb_pgssm(
        stsm(
            x0,
            s2_trend,
            s2_speed,
            s2_seasonal,
            n,
            Sigma0,
            omega2,
            s_order,
            alpha,
        ),
        r,
    )
    return model

# %% ../nbs/20_pgssm.ipynb 12
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
    model: PGSSM
):
    x0, A, Sigma, B, dist, xi = model
    px = log_probs_x(x, GLSSMState(x0, A, Sigma)).sum()
    py = log_probs_y(x, y, B, dist, xi).sum()
    return px + py
