# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/10_kalman_filter_smoother.ipynb.

# %% auto 0
__all__ = ['State', 'StateCov', 'StateTransition', 'simulate_glssm', 'predict', 'filter', 'kalman', 'gnll', 'smooth', 'smoother',
           'sqrt_predict', 'sqrt_filter', 'sqrt_smooth_step', 'sqrt_smoother']

# %% ../nbs/10_kalman_filter_smoother.ipynb 3
import jax.numpy as jnp
import jax.random as jrn
from jax import vmap
from jax.lax import scan
import tensorflow_probability.substrates.jax.distributions as tfd

def simulate_glssm(x0, A, B, Sigma, Omega, N, key):
    vmatmul = vmap(jnp.matmul, (None, 0))

    def sim_next_states(carry, inputs):
        x_prev, key = carry
        A, Sigma = inputs

        next_loc = vmatmul(A, x_prev)
        key, subkey = jrn.split(key)

        samples = tfd.MultivariateNormalFullCovariance(next_loc, Sigma).sample(seed=subkey)

        return (samples, key), samples
    
    m, = x0.shape
    A_ext = jnp.concatenate(
        (jnp.eye(m)[jnp.newaxis], A)
    )

    x0_recast = jnp.broadcast_to(x0, (N, m))
    key, subkey = jrn.split(key)
    _, X = scan(sim_next_states, (x0_recast, subkey), (A_ext, Sigma))
    
    S = vmap(vmatmul, (0,0))(B, X)

    # samples x time x space
    X = X.transpose((1, 0, 2))

    S = S.transpose((1, 0, 2))
    
    key, subkey = jrn.split(key)
    Y = tfd.MultivariateNormalFullCovariance(S, Omega).sample(seed=subkey)

    return X, Y

# %% ../nbs/10_kalman_filter_smoother.ipynb 9
import jax.numpy as jnp
from jaxtyping import Float, Array
import jax.scipy.linalg as jsla
from jax.lax import scan
from jax import vmap

import tensorflow_probability.substrates.jax.distributions as tfd


def predict(
    x_filt: Float[Array, "m"],
    Xi_filt: Float[Array, "m m"],
    A: Float[Array, "m m"],
    B: Float[Array, "p m"],
    Sigma: Float[Array, "m m"],
    Omega: Float[Array, "p p"],
):
    x_pred = A @ x_filt
    Xi_pred = A @ Xi_filt @ A.T + Sigma

    y_pred = B @ x_pred
    Psi_pred = B @ Xi_pred @ B.T + Omega

    return x_pred, Xi_pred, y_pred, Psi_pred


def filter(
    x_pred: Float[Array, "m"],
    Xi_pred: Float[Array, "m m"],
    y_pred: Float[Array, "p"],
    Psi_pred: Float[Array, "p p"],
    y: Float[Array, "p"],
    B: Float[Array, "p m"],
):
    K = Xi_pred @ jsla.solve(Psi_pred, B).T
    x_filt = x_pred + K @ (y - y_pred)
    Xi_filt = Xi_pred - K @ Psi_pred @ K.T

    return x_filt, Xi_filt


def kalman(
    y: Float[Array, "n+1 p"],
    x0: Float[Array, "m"],
    Sigma: Float[Array, "n+1 m m"],
    Omega: Float[Array, "n+1 p p"],
    A: Float[Array, "n m m"],
    B: Float[Array, "n+1 p m"],
):
    def step(carry, inputs):
        x_filt, Xi_filt = carry
        y, Sigma, Omega, A, B = inputs

        x_pred, Xi_pred, y_pred, Psi_pred = predict(x_filt, Xi_filt, A, B, Sigma, Omega)
        x_filt_next, Xi_filt_next = filter(x_pred, Xi_pred, y_pred, Psi_pred, y, B)

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

    return x_filt, Xi_filt, x_pred, Xi_pred

# %% ../nbs/10_kalman_filter_smoother.ipynb 11
def gnll(y, x_pred, Xi_pred, B, Omega):
    vmatmul = vmap(jnp.matmul, (0,0))
    y_pred = vmatmul(B, x_pred)
    Psi_pred = vmatmul(vmatmul(B, Xi_pred), jnp.transpose(B, (0, 2, 1))) + Omega
    
    return tfd.MultivariateNormalFullCovariance(y_pred, Psi_pred).log_prob(y).sum()

# %% ../nbs/10_kalman_filter_smoother.ipynb 14
State = Float[Array, "m"]
StateCov = Float[Array, "m m"]
StateTransition = Float[Array, "m m"]


def smooth(
    x_filt: State,
    x_pred_next: State,
    x_smooth_next: State,
    Xi_filt: StateCov,
    Xi_pred_next: StateCov,
    Xi_smooth_next: StateCov,
    A: StateTransition
):
    err = x_smooth_next - x_pred_next
    Gain = Xi_filt @ jsla.solve(Xi_pred_next, A).T

    x_smooth = x_filt + Gain @ err
    Xi_smooth = Xi_filt - Gain @ (Xi_pred_next - Xi_smooth_next) @ Gain.T

    return (x_smooth, Xi_smooth)


def smoother(
    x_filt: Float[Array, "n+1 m"],
    Xi_filt: Float[Array, "n+1 m m"],
    x_pred: Float[Array, "n+1 m"],
    Xi_pred: Float[Array, "n+1 m m"],
    A: Float[Array, "n m m"]
):
    def step(carry, inputs):
        x_smooth_next, Xi_smooth_next = carry
        x_filt, Xi_filt, x_pred_next, Xi_pred_next, A = inputs

        x_smooth, Xi_smooth = smooth(
            x_filt, x_pred_next, x_smooth_next, Xi_filt, Xi_pred_next, Xi_smooth_next,A
        )

        return (x_smooth, Xi_smooth), (x_smooth, Xi_smooth)

    _, (x_smooth, Xi_smooth) = scan(
        step, (x_filt[-1], Xi_filt[-1]), (x_filt[:-1], Xi_filt[:-1], x_pred[1:], Xi_pred[1:], A), reverse=True
    )

    x_smooth = jnp.concatenate([x_smooth, x_filt[None, -1]])
    Xi_smooth = jnp.concatenate([Xi_smooth, Xi_filt[None, -1]])

    return x_smooth, Xi_smooth

# %% ../nbs/10_kalman_filter_smoother.ipynb 21
def sqrt_predict(x_filt, cu_Xi_filt, A, cu_Sigma):
    x_pred = A @ x_filt
    matrix_to_rotate = jnp.block([
        [cu_Sigma, jnp.zeros_like(cu_Sigma)],
        [cu_Xi_filt @ A.T, cu_Xi_filt]
    ])

    Q_pred, R_pred = jnp.linalg.qr(matrix_to_rotate)
    m, = x_filt.shape

    cu_Xi_pred = R_pred[:m,:m]
    G = jsla.solve_triangular(cu_Xi_pred, R_pred[:m,m:], lower=False).T

    cu_H = R_pred[m:, m:]
    
    return x_pred, cu_Xi_pred, G, cu_H

# %% ../nbs/10_kalman_filter_smoother.ipynb 24
def sqrt_filter(x_pred, cu_Xi_pred, cu_Omega, B, y):
    y_pred = B @ x_pred

    p, m = B.shape

    matrix_to_rotate = jnp.block([
        [cu_Omega, jnp.zeros((p,m))],
        [cu_Xi_pred @ B.T, cu_Xi_pred]
    ])

    Q_filt, R_filt = jnp.linalg.qr(matrix_to_rotate)

    cu_Psi_pred = R_filt[:p, :p]
    K = jsla.solve_triangular(cu_Psi_pred, R_filt[:p, p:], lower=False).T
    cu_Xi_filt = R_filt[p:,p:]

    x_filt = x_pred + K @ (y - y_pred)

    return x_filt, cu_Xi_filt


# %% ../nbs/10_kalman_filter_smoother.ipynb 29
def sqrt_smooth_step(
    x_filt: State,
    x_pred_next: State,
    x_smooth_next: State,
    cu_Xi_smooth_next: StateCov,
    G: Float[Array, "m m"],
    cu_H: Float[Array, "m m"]
):
    m, = x_filt.shape
    err = x_smooth_next - x_pred_next

    x_smooth = x_filt + G @ err
    matrix_to_rotate = jnp.block([
        [cu_Xi_smooth_next @ G],
        [cu_H]
    ])

    Q_smooth, R_smooth = jnp.linalg.qr(matrix_to_rotate)

    cu_Xi_smooth = R_smooth[:m,:m]

    return (x_smooth, cu_Xi_smooth)

def sqrt_smoother(
    x_filt: Float[Array, "n+1 m"],
    cu_Xi_filt: Float[Array, "n+1 m m"],
    x_pred: Float[Array, "n+1 m"],
    cu_Xi_pred: Float[Array, "n+1 m m"],
    G: Float[Array, "n m m"],
    cu_H: Float[Array, "n m m"]
):
    def step(carry, inputs):
        x_smooth_next, cu_Xi_smooth_next = carry
        x_filt, x_pred_next, G, cu_H = inputs

        x_smooth, cu_Xi_smooth = sqrt_smooth_step(
            x_filt, x_pred_next, x_smooth_next, cu_Xi_smooth_next, G, cu_H
        )

        return (x_smooth, cu_Xi_smooth), (x_smooth, cu_Xi_smooth)

    _, (x_smooth, Xi_smooth) = scan(
        step, (x_filt[-1], cu_Xi_filt[-1]), (x_filt[:-1], x_pred[1:], G, cu_H), reverse=True
    )

    x_smooth = jnp.concatenate([x_smooth, x_filt[None, -1]])
    cu_Xi_smooth = jnp.concatenate([cu_Xi_smooth, cu_Xi_filt[None, -1]])

    return x_smooth, cu_Xi_smooth
