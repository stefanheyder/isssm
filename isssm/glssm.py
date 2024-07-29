# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/00_glssm.ipynb.

# %% auto 0
__all__ = ['vmatmul', 'simulate_states', 'simulate_glssm', 'simulate_smoothed_FW1994', 'FFBS', 'log_probs_x', 'log_probs_y',
           'log_prob']

# %% ../nbs/00_glssm.ipynb 1
import jax.numpy as jnp
import jax.random as jrn
from jax import vmap
from jax.lax import scan
from jaxtyping import Array, Float, PRNGKeyArray

from .kalman import kalman
from .typing import (GLSSM, GLSSMObservationModel, GLSSMState,
                          Observations, States)
from .util import MVN_degenerate as MVN

# %% ../nbs/00_glssm.ipynb 6
vmatmul = vmap(jnp.matmul, (None, 0))

def simulate_states(
    state: GLSSMState,
    N: int, # number of samples to draw
    key: PRNGKeyArray # the random state
) -> Float[Array, "N n+1 m"]: # array of N samples from the state distribution  
    """Simulate states of a GLSSM """
    x0, A, Sigma = state

    def sim_next_states(carry, inputs):
        x_prev, key = carry
        A, Sigma = inputs

        next_loc = vmatmul(A, x_prev)

        key, subkey = jrn.split(key)
        samples = MVN(next_loc, Sigma).sample(seed=subkey)

        return (samples, key), samples

    (m,) = x0.shape
    A_ext = jnp.concatenate((jnp.eye(m)[jnp.newaxis], A))

    x0_recast = jnp.broadcast_to(x0, (N, m))
    key, subkey = jrn.split(key)

    _, X = scan(sim_next_states, (x0_recast, subkey), (A_ext, Sigma))

    return X.transpose((1, 0, 2))

# %% ../nbs/00_glssm.ipynb 7
def simulate_glssm(
    glssm: GLSSM,
    N: int, # number of sample paths
    key: PRNGKeyArray # the random state
) -> (Float[Array, "N n+1 m"], Float[Array, "N n+1 p"]): # tuple of two arrays each with of N samples from the state/observation distribution
    """Simulate states and observations of a GLSSM """
    x0, A, Sigma, B, Omega = glssm
    key, subkey = jrn.split(key)
    X = simulate_states(GLSSMState(x0, A, Sigma), N, subkey).transpose((1, 0, 2))

    S = vmap(vmatmul, (0, 0))(B, X)

    # samples x time x space
    X = X.transpose((1, 0, 2))

    S = S.transpose((1, 0, 2))

    key, subkey = jrn.split(key)
    Y = MVN(S, Omega).sample(seed=subkey)

    return X, Y

# %% ../nbs/00_glssm.ipynb 12
def simulate_smoothed_FW1994(
    x_filt: Float[Array, "n+1 m"],
    Xi_filt: Float[Array, "n+1 m m"],
    Xi_pred: Float[Array, "n+1 m m"],
    A: Float[Array, "n m m"],
    N: int, # number of samples
    key: PRNGKeyArray # the random states
) -> Float[Array, "N n+1 m"]: # array of N samples from the smoothing distribution
    r"""Simulate from smoothing distribution $p(X_0, \dots, X_n|Y_0, \dots, Y_n)$"""

    key, subkey = jrn.split(key)
    X_n = MVN(x_filt[-1], Xi_filt[-1]).sample(N, subkey)

    def sample_backwards(carry, inputs):
        X_smooth_next, key = carry
        x_filt, Xi_filt, Xi_pred, A = inputs

        G = Xi_filt @ jnp.linalg.solve(Xi_pred, A).T

        cond_expectation = x_filt + vmatmul(G, X_smooth_next - (A @ x_filt)[None])
        cond_covariance = Xi_filt - G @ Xi_pred @ G.T

        key, subkey = jrn.split(key)
        new_samples = MVN(cond_expectation, cond_covariance).sample(seed=subkey)
        return (new_samples, key), new_samples

    key, subkey = jrn.split(key)
    _, X = scan(
        sample_backwards,
        (X_n, subkey),
        (x_filt[:-1], Xi_filt[:-1], Xi_pred[1:], A),
        reverse=True,
    )

    X_full = jnp.concatenate((X, X_n[None]))

    return X_full.transpose((1, 0, 2))


def FFBS(
    y: Observations, # Observations $y$
    glssm: GLSSM, # GLSSM
    N: int, # number of samples 
    key: PRNGKeyArray # random state
) -> Float[Array, "N n+1 m"]: # N samples from the smoothing distribution
    r"""The Forward-Filter Backwards-Sampling Algorithm from [@Fruhwirth-Schnatter1994Data]."""

    x0, A, Sigma, B, Omega = glssm
    x_filt, Xi_filt, _, Xi_pred = kalman(y, GLSSM(x0, A, Sigma, B, Omega))

    key, subkey = jrn.split(key)
    return simulate_smoothed_FW1994(x_filt, Xi_filt, Xi_pred, A, N, subkey)

# %% ../nbs/00_glssm.ipynb 17
def log_probs_x(
    x: States,  # the states
    state: GLSSMState # the state model
) -> Float[Array, "n+1"]:  # log probabilities $p(x_t | x_{t-1})$
    """log probabilities $\\log p(x_t | x_{t-1})$"""
    x0, A, Sigma = state
    (m,) = x0.shape
    A_ext = jnp.concatenate((jnp.eye(m)[jnp.newaxis], A))
    x_prev = jnp.concatenate((x0[None], x[:-1]))
    x_pred = (A_ext @ x_prev[:, :, None])[:,:,0]
    return MVN(x_pred, Sigma).log_prob(x)


def log_probs_y(
    y: Observations,  # the observations
    x: States,  # the states
    obs_model: GLSSMObservationModel, # the observation model
) -> Float[Array, "n+1"]:  # log probabilities $p(y_t | x_t)$
    """log probabilities $\\log p(y_t | x_t)$"""
    B, Omega = obs_model
    y_pred = (B @ x[:, :, None])[:, :, 0]
    return MVN(y_pred, Omega).log_prob(y)

def log_prob(
    x: States,
    y: Observations,
    glssm: GLSSM
) -> Float: # $\\log p(x,y)$
    """joint log probability of states and observations"""
    x0, A, Sigma, B, Omega = glssm
    log_p_x = jnp.sum(log_probs_x(x, GLSSMState(x0, A, Sigma)))
    log_p_y_given_x = jnp.sum(log_probs_y(y, x, GLSSMObservationModel(B, Omega)))
    return log_p_x + log_p_y_given_x
