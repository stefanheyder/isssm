# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/99_optimization.ipynb.

# %% auto 0
__all__ = ['converged']

# %% ../nbs/99_optimization.ipynb 1
import jax.numpy as jnp

def converged(new, old, eps):
    is_close = jnp.max(jnp.abs((new - old)/old)) < eps
    any_nans = jnp.isnan(new).sum() > 0
    return jnp.logical_or(is_close, any_nans)
