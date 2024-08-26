# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/Models/00_gaussian_models.ipynb.

# %% auto 0
__all__ = ['lcm', 'ar1', 'mv_ar1']

# %% ../../nbs/Models/00_gaussian_models.ipynb 4
import jax.numpy as jnp
from jaxtyping import Float, Array
from ..typing import GLSSM


def lcm(
    n: int,  # number of time steps
    x0: Float,  # initial value
    s2_x0: Float,  # initial variance
    s2_eps: Float,  # innovation variance
    s2_eta: Float,  # observation noise variance
) -> GLSSM:  # the locally constant model
    A = jnp.ones((n, 1, 1))
    B = jnp.ones((n + 1, 1, 1))
    D = jnp.ones((n, 1, 1))

    Sigma0 = s2_x0 * jnp.ones((1, 1))
    Sigma = s2_eps * jnp.ones((n, 1, 1))
    Omega = jnp.ones((n + 1, 1, 1)) * s2_eta

    u = jnp.zeros((n + 1, 1)).at[0].set(x0)
    v = jnp.zeros((n + 1, 1))
    return GLSSM(u, A, D, Sigma0, Sigma, v, B, Omega)

# %% ../../nbs/Models/00_gaussian_models.ipynb 7
def ar1(
    mu: Float,  # stationary mean
    tau2: Float,  # stationary variance
    alpha,  # dampening factor
    omega2,  # observation noise
    n: int,  # number of time steps
) -> GLSSM:
    x0 = jnp.array([mu])
    A = jnp.tile(alpha * jnp.eye(1)[None], (n, 1, 1))
    B = jnp.tile(jnp.eye(1)[None], (n + 1, 1, 1))

    sigma2 = (1 - alpha**2) * tau2
    Sigma0 = tau2 * jnp.ones((1, 1, 1))
    Sigma = sigma2 * jnp.ones((n, 1, 1))

    Omega = omega2 * jnp.ones((n + 1, 1, 1))

    u = jnp.zeros((n + 1, 1)).at[0].set(x0)
    v = jnp.zeros((n + 1, 1))
    D = jnp.broadcast_to(jnp.eye(1)[None], (n, 1, 1))

    return GLSSM(u, A, D, Sigma0, Sigma, v, B, Omega)

# %% ../../nbs/Models/00_gaussian_models.ipynb 9
def mv_ar1(
    mu: Float[Array, "m"],  # stationary mean
    Tau: Float[Array, "m m"],  # stationary covariance
    alpha: Float,  # dampening factor
    omega2: Float,  # observation noise
    n: int,  # number of time steps
) -> GLSSM:
    x0 = mu
    (m,) = mu.shape

    A = jnp.broadcast_to(alpha * jnp.eye(m)[None], (n, m, m))
    B = jnp.broadcast_to(jnp.eye(m)[None], (n + 1, m, m))

    Sigma0 = Tau
    Sigma = jnp.broadcast_to((1 - alpha**2) * Tau * jnp.eye(m), (n, m, m))
    Omega = jnp.broadcast_to(omega2 * jnp.eye(m)[None], (n + 1, m, m))
    u = jnp.zeros((n + 1, m)).at[0].set(x0)
    v = jnp.zeros((n + 1, m))
    D = jnp.broadcast_to(jnp.eye(m), (n, m, m))
    return GLSSM(u, A, D, Sigma0, Sigma, v, B, Omega)
