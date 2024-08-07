# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/Models/00_gaussian_models.ipynb.

# %% auto 0
__all__ = ['lcm', 'common_factor_lcm', 'ar1', 'mv_ar1']

# %% ../../nbs/Models/00_gaussian_models.ipynb 4
import jax.numpy as jnp
from jaxtyping import Float, Array
from ..typing import GLSSM


def lcm(
    n: int,  # number of time steps
    x0: Float, # initial value
    s2_x0: Float, # initial variance
    s2_eps: Float, # innovation variance
    s2_eta: Float, # observation noise variance
) -> GLSSM: # the locally constant model
    A = jnp.ones((n, 1, 1))
    B = jnp.ones((n + 1, 1, 1))

    Sigma = jnp.concatenate((s2_x0 * jnp.ones((1, 1, 1)), s2_eps * jnp.ones((n, 1, 1))))
    Omega = jnp.ones((n + 1, 1, 1)) * s2_eta

    x0 = jnp.array(x0).reshape((1,))

    return GLSSM(x0, A, Sigma, B, Omega)

# %% ../../nbs/Models/00_gaussian_models.ipynb 7
def common_factor_lcm(
    n: int,  # number of time steps
    x0: Float[Array, "3"], # initial state mean
    Sigma0: Float[Array, "3 3"], # initial state covariance
    s2_eps: Float, # innovation variance
    s2_eta: Float, # observation noise variance
) -> GLSSM:
    if x0.shape != (3,):
        raise ValueError(
            f"x0 does not have the correct shape, expected (3,) but got {x0.shape}"
        )

    A = jnp.broadcast_to(jnp.eye(3), (n, 3, 3))
    B = jnp.broadcast_to(jnp.array([[1, 0, 1], [0, 1, 1]]), (n + 1, 2, 3))
    Sigma = jnp.concatenate(
        (Sigma0[None], s2_eps * jnp.broadcast_to(jnp.eye(3), (n, 3, 3)))
    )
    Omega = s2_eta * jnp.broadcast_to(jnp.eye(2), (n + 1, 2, 2))

    return GLSSM(x0, A, Sigma, B, Omega)

# %% ../../nbs/Models/00_gaussian_models.ipynb 10
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
    Sigma = jnp.concatenate((tau2 * jnp.ones((1, 1, 1)), sigma2 * jnp.ones((n, 1, 1))))

    Omega = omega2 * jnp.ones((n + 1, 1, 1))

    return GLSSM(x0, A, Sigma, B, Omega)

# %% ../../nbs/Models/00_gaussian_models.ipynb 12
def mv_ar1(
    mu: Float[Array, "m"],  # stationary mean
    Tau: Float[Array, "m m"],  # stationary covariance
    alpha: Float,  # dampening factor
    omega2: Float,  # observation noise
    n: int,  # number of time steps
) -> GLSSM:
    x0 = mu
    m, = mu.shape

    A = jnp.broadcast_to(alpha * jnp.eye(m)[None], (n, m, m))
    B = jnp.broadcast_to(jnp.eye(m)[None], (n + 1, m, m))

    Sigma = jnp.concatenate(
        (Tau[None], jnp.broadcast_to((1 - alpha**2) * Tau * jnp.eye(m), (n, m,m)))
    )
    Omega = jnp.broadcast_to(omega2 * jnp.eye(m)[None], (n + 1, m, m))
    return GLSSM(x0, A, Sigma, B, Omega)
