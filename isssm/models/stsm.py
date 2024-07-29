# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/models/10_stsm.ipynb.

# %% auto 0
__all__ = ['stsm']

# %% ../../nbs/models/10_stsm.ipynb 1
import jax
import jax.numpy as jnp
from jaxtyping import Float, Array
from ..typing import GLSSM
import jax.scipy as jsp

# %% ../../nbs/models/10_stsm.ipynb 5
def stsm(
    x0: Float[Array, "m"], # initial state
    s2_mu: Float, # variance of trend innovations
    s2_nu: Float, # variance of velocity innovations
    s2_seasonal: Float, # variance of velocity innovations
    n: int, # number of time points
    Sigma_init: Float[Array, "m m"], # initial state covariance
    o2: Float, # variance of observation noise
    s_order: int, # order of seasonal component
) -> GLSSM:

    A = jnp.array([[1, 1], [0, 1]])
    B = jnp.array([[1, 0]])

    Sigma = jnp.diag(jnp.array([s2_mu, s2_nu]))


    if s_order >= 2:
        A_seasonal = jnp.block([
            [-jnp.ones((s_order - 1)), -jnp.ones((1,))],
            [jnp.eye(s_order - 1), jnp.zeros((s_order - 1,))]
        ])
        B_seasonal = (jnp.eye(s_order)[0])[None,:]
        Sigma_seasonal = jnp.diag(jnp.eye(s_order)[0] * s2_seasonal)

        A = jsp.linalg.block_diag(A, A_seasonal)
        B = jnp.concatenate((B, B_seasonal), axis=1)
        Sigma = jsp.linalg.block_diag(Sigma, Sigma_seasonal)
        
    
    A = jnp.broadcast_to(A, (n, s_order + 2, s_order + 2))
    B = jnp.broadcast_to(B, (n+1, 1, s_order + 2))
    Sigma = jnp.broadcast_to(Sigma, (n, s_order + 2, s_order + 2))
    Sigma = jnp.concatenate((Sigma_init[None, :, :], Sigma), axis=0)

    Omega = jnp.broadcast_to(jnp.diag(jnp.array([o2])), (n + 1, 1, 1))

    return GLSSM(x0, A, Sigma, B, Omega)
