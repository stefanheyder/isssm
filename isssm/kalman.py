# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/10_kalman_filter_smoother.ipynb.

# %% auto 0
__all__ = ['State', 'StateCov', 'StateTransition', 'kalman', 'smoother', 'FFBS', 'disturbance_smoother', 'smoothed_signals',
           'simulation_smoother']

# %% ../nbs/10_kalman_filter_smoother.ipynb 1
import jax.numpy as jnp
import jax.random as jrn
import jax.scipy.linalg as jsla
import tensorflow_probability.substrates.jax.distributions as tfd
from jax import vmap, jit
from jax.lax import scan
from jaxtyping import Array, Float, PRNGKeyArray

from .typing import GLSSM, FilterResult, Observations, SmootherResult
from .util import MVN_degenerate as MVN, vmatmul

# %% ../nbs/10_kalman_filter_smoother.ipynb 8
def _predict(
    x_filt: Float[Array, "m"], # $X_{t|t}$
    Xi_filt: Float[Array, "m m"], # $\Xi_{t|t}
    A: Float[Array, "m m"], # $A_t$
    Sigma: Float[Array, "m m"], # $\Sigma_{t + 1}
):
    """perform a single prediction step"""
    x_pred = A @ x_filt
    Xi_pred = A @ Xi_filt @ A.T + Sigma

    return x_pred, Xi_pred


def _filter(
    x_pred: Float[Array, "m"], 
    Xi_pred: Float[Array, "m m"],
    y: Float[Array, "p"],
    B: Float[Array, "p m"],
    Omega: Float[Array, "p p"],
):
    """perform a single filtering step"""
    y_pred = B @ x_pred
    Psi_pred = B @ Xi_pred @ B.T + Omega
    K = Xi_pred @ B.T @ jnp.linalg.pinv(Psi_pred)#jsla.solve(Psi_pred, B).T
    x_filt = x_pred + K @ (y - y_pred)
    Xi_filt = Xi_pred - K @ Psi_pred @ K.T

    return x_filt, Xi_filt


def kalman(
    y: Observations, # observatoins
    glssm: GLSSM, # model
) -> FilterResult: # filtered & predicted states and covariances
    """Perform the Kalman filter"""
    x0, A, Sigma, B, Omega = glssm
    def step(carry, inputs):
        x_filt, Xi_filt = carry
        y, Sigma, Omega, A, B = inputs

        x_pred, Xi_pred = _predict(x_filt, Xi_filt, A, Sigma)
        x_filt_next, Xi_filt_next = _filter(x_pred, Xi_pred, y, B, Omega)

        return (x_filt_next, Xi_filt_next), (x_filt_next, Xi_filt_next, x_pred, Xi_pred)

    # artificial state X_{-1} with mean x_0
    # covariance zero, transition identity
    # will lead to X_0 having correct predictive distribution
    # this avoids having to compute a separate filtering step beforehand

    m, = x0.shape
    A_ext = jnp.concatenate(
        (jnp.eye(m)[jnp.newaxis], A)
    )

    _, (x_filt, Xi_filt, x_pred, Xi_pred) = scan(
        step, (x0, jnp.zeros_like(Sigma[0])), (y, Sigma, Omega, A_ext, B)
    )

    return FilterResult(x_filt, Xi_filt, x_pred, Xi_pred)

# %% ../nbs/10_kalman_filter_smoother.ipynb 13
State = Float[Array, "m"]
StateCov = Float[Array, "m m"]
StateTransition = Float[Array, "m m"]


def _smooth_step(
    x_filt: State,
    x_pred_next: State,
    x_smooth_next: State,
    Xi_filt: StateCov,
    Xi_pred_next: StateCov,
    Xi_smooth_next: StateCov,
    A: StateTransition
):
    err = x_smooth_next - x_pred_next
    Gain = Xi_filt @ A.T @ jnp.linalg.pinv(Xi_pred_next)

    x_smooth = x_filt + Gain @ err
    Xi_smooth = Xi_filt - Gain @ (Xi_pred_next - Xi_smooth_next) @ Gain.T

    return (x_smooth, Xi_smooth)


def smoother(
    filter_result: FilterResult,
    A: Float[Array, "n m m"] # transition matrices
) -> SmootherResult:
    """perform the Kalman smoother"""
    x_filt, Xi_filt, x_pred, Xi_pred = filter_result
    def step(carry, inputs):
        x_smooth_next, Xi_smooth_next = carry
        x_filt, Xi_filt, x_pred_next, Xi_pred_next, A = inputs

        x_smooth, Xi_smooth = _smooth_step(
            x_filt, x_pred_next, x_smooth_next, Xi_filt, Xi_pred_next, Xi_smooth_next,A
        )

        return (x_smooth, Xi_smooth), (x_smooth, Xi_smooth)

    _, (x_smooth, Xi_smooth) = scan(
        step, (x_filt[-1], Xi_filt[-1]), (x_filt[:-1], Xi_filt[:-1], x_pred[1:], Xi_pred[1:], A), reverse=True
    )

    x_smooth = jnp.concatenate([x_smooth, x_filt[None, -1]])
    Xi_smooth = jnp.concatenate([Xi_smooth, Xi_filt[None, -1]])

    return SmootherResult(x_smooth, Xi_smooth)

# %% ../nbs/10_kalman_filter_smoother.ipynb 18
def _simulate_smoothed_FW1994(
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
    model: GLSSM, # GLSSM
    N: int, # number of samples 
    key: PRNGKeyArray # random state
) -> Float[Array, "N n+1 m"]: # N samples from the smoothing distribution
    r"""The Forward-Filter Backwards-Sampling Algorithm from [@Fruhwirth-Schnatter1994Data]."""
    x_filt, Xi_filt, _, Xi_pred = kalman(y, model)

    key, subkey = jrn.split(key)
    return _simulate_smoothed_FW1994(x_filt, Xi_filt, Xi_pred, model.A, N, subkey)

# %% ../nbs/10_kalman_filter_smoother.ipynb 23
def disturbance_smoother(
    filtered: FilterResult, # filter result
    y: Observations, # observations
    model: GLSSM # model
) -> Float[Array, "n+1 p"]: # smoothed disturbances
    """perform the disturbance smoother for observation disturbances only"""
    x_filt, Xi_filt, x_pred, Xi_pred = filtered
    x0, A, Sigma, B, Omega = model
    np1, p, m = B.shape

    def step(carry, inputs):
        (r,) = carry
        y_tilde, A, B, Omega, Xi_pred = inputs

        Psi_pred = B @ Xi_pred @ B.T + Omega
        Psi_pred_pinv = jnp.linalg.pinv(Psi_pred)
        K = Xi_pred @ B.T @ Psi_pred_pinv

        eta_smooth = Omega @ (Psi_pred_pinv @ y_tilde - K.T @ A.T @ r)
        L = A @ (jnp.eye(m) - K @ B)

        r_prev = B.T @ Psi_pred_pinv @ y_tilde + L.T @ r

        return (r_prev,), (eta_smooth, Psi_pred_pinv, K,L)

    y_tilde = y - vmap(jnp.matmul)(B, x_pred)

    A_ext = jnp.concatenate((A, jnp.eye(m)[jnp.newaxis]), axis=0)
    _, (eta_smooth, Psi_pred_pinv, K, L) = scan(
        step, (jnp.zeros(m),), (y_tilde, A_ext, B, Omega, Xi_pred), reverse=True
    )

    return eta_smooth, (Psi_pred_pinv, K, L)

def smoothed_signals(
    filtered: FilterResult, # filter result
    y: Observations, # observations
    model: GLSSM # model
) -> Float[Array, "n+1 m"]: # smoothed signals
    """compute smoothed signals from filter result"""
    eta_smooth, _ = disturbance_smoother(filtered, y, model)
    return y - eta_smooth

# %% ../nbs/10_kalman_filter_smoother.ipynb 28
def _sim_from_innovations_disturbances(
    model: GLSSM, eps: Float[Array, "N n+1 m"], eta: Float[Array, "N n+1 p"]
) -> Float[Array, "N n+1 p"]:
    x0, A, Sigma, B, Omega = model
    N, np1, m = eps.shape

    def step(carry, inputs):
        (x,) = carry
        A, B, eps, eta = inputs

        x_next = (A @ x[..., None])[..., 0] + eps
        y_next = (B @ x[..., None])[..., 0] + eta

        return (x_next,), y_next

    A_ext = jnp.concatenate((jnp.eye(m)[None], A), axis=0)
    (x,), y = scan(
        step,
        (jnp.broadcast_to(x0, (N, m)),),
        (A_ext, B, eps.transpose((1, 0, 2)), eta.transpose(1, 0, 2)),
    )

    return y.transpose((1, 0, 2))


def simulation_smoother(
    model: GLSSM,  # model
    y: Observations,  # observations
    N: int,  # number of samples to draw
    key: PRNGKeyArray,  # random number seed
) -> Float[Array, "N n+1 m"]:  # N samples from the smoothing distribution of signals
    """Simulate from the smoothing distribution of signals"""
    np1, p, m = model.B.shape

    @jit
    def signal_filter_smoother(y, model):
        return smoothed_signals(kalman(y, model), y, model)

    key, subkey = jrn.split(key)
    eps = MVN(jnp.zeros((np1, m)), model.Sigma).sample(N, subkey)
    key, subkey = jrn.split(key)
    eta = MVN(jnp.zeros((np1, p)), model.Omega).sample(N, subkey)

    y_sim = _sim_from_innovations_disturbances(model, eps, eta)

    signals_smooth = signal_filter_smoother(y, model)
    sim_signals = y_sim - eta
    sim_signals_smooth = vmap(signal_filter_smoother, (0, None))(y_sim, model)

    return (sim_signals - sim_signals_smooth) + signals_smooth[None]
