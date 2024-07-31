# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/99_util.ipynb.

# %% auto 0
__all__ = ['LOFM', 'LOLT', 'mm_sim', 'mm_time', 'mm_time_sim', 'degenerate_cholesky', 'MVN_degenerate', 'converged']

# %% ../nbs/99_util.ipynb 2
import jax.numpy as jnp
from jax import vmap
from jaxtyping import Array, Float, Bool
import tensorflow_probability.substrates.jax as tfp
from tensorflow_probability.substrates.jax.distributions import MultivariateNormalLinearOperator as MVNLO


# %% ../nbs/99_util.ipynb 6
LOFM = tfp.tf2jax.linalg.LinearOperatorFullMatrix
LOLT = tfp.tf2jax.linalg.LinearOperatorLowerTriangular
def degenerate_cholesky(Sigma): 
    evals, evecs = jnp.linalg.eigh(Sigma)
    # transpose for QR
    # ensure positive eigenvalues
    sqrt_cov = jnp.einsum('...ij,...j->...ji', evecs, jnp.sqrt(jnp.abs(evals)))
    Q, R = jnp.linalg.qr(sqrt_cov, mode='complete')
    # ensure positive diagonal
    R = R * jnp.sign(jnp.einsum('...ii->...i', R)[..., None])
    L = R.swapaxes(-1, -2)
    return L

def MVN_degenerate(loc: Array, cov: Array) -> tfp.distributions.MultivariateNormalLinearOperator:
    L = degenerate_cholesky(cov)
    return MVNLO(loc=loc, scale=LOLT(L))

# %% ../nbs/99_util.ipynb 10
def converged(
    new: Float[Array, "..."],  # the new array
    old: Float[Array, "..."],  # the old array
    eps: Float,  # tolerance
) -> Bool:  # whether the arrays are close enough
    """check that sup-norm of relative change is smaller than tolerance"""
    is_close = jnp.max(jnp.abs((new - old) / old)) < eps
    any_nans = jnp.isnan(new).sum() > 0
    return jnp.logical_or(is_close, any_nans)

# %% ../nbs/99_util.ipynb 12
# matmul with $A_t$ and $X^i_t$
mm_sim = vmap(jnp.matmul, (None, 0))
# matmul with $(A_t)_{t}$ and $(X_t)_{t}$
mm_time = vmap(jnp.matmul, (0, 0))
# matmul with $(A_t)_{t}$ and $(X^i_t)_{i,t}$
mm_time_sim = vmap(mm_time, (None, 0))
