# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/60_maximum_likelihood_estimation.ipynb.

# %% auto 0
__all__ = ['vmm', 'gnll', 'mle_glssm']

# %% ../nbs/60_maximum_likelihood_estimation.ipynb 2
import jax.numpy as jnp
import jax.random as jrn
from jax import vmap

# %% ../nbs/60_maximum_likelihood_estimation.ipynb 5
vmm = vmap(jnp.matmul, (0,0))

def gnll(y, x_pred, Xi_pred, B, Omega):
    y_pred = vmm(B, x_pred)
    Psi_pred = vmm(vmm(B, Xi_pred), jnp.transpose(B, (0, 2, 1))) + Omega
    
    return - tfd.MultivariateNormalFullCovariance(y_pred, Psi_pred).log_prob(y).sum()

# %% ../nbs/60_maximum_likelihood_estimation.ipynb 8
from jax.scipy.optimize import minimize
def mle_glssm(y, model, theta0, aux):
    def f(theta):
        x0, A, B, Sigma, Omega = model(theta, aux)
        _, _, x_pred, Xi_pred = kalman(y, x0, Sigma, Omega, A, B)
        return gnll(y, x_pred, Xi_pred, B, Omega)

    return minimize(f, theta0, method='BFGS')
