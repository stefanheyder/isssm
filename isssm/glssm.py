# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/00_glssm.ipynb.

# %% auto 0
__all__ = ['vmatmul', 'simulate_glssm', 'simulate_smoothed']

# %% ../nbs/00_glssm.ipynb 3
import jax.numpy as jnp
import jax.random as jrn
from jax import vmap
from jax.lax import scan
from tensorflow_probability.substrates.jax.distributions import MultivariateNormalFullCovariance as MVN

# %% ../nbs/00_glssm.ipynb 4
vmatmul = vmap(jnp.matmul, (None, 0))

def simulate_glssm(x0, A, B, Sigma, Omega, N, key):

    def sim_next_states(carry, inputs):
        x_prev, key = carry
        A, Sigma = inputs

        next_loc = vmatmul(A, x_prev)
        key, subkey = jrn.split(key)

        samples = MVN(next_loc, Sigma).sample(seed=subkey)

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
    Y = MVN(S, Omega).sample(seed=subkey)

    return X, Y

# %% ../nbs/00_glssm.ipynb 8
def simulate_smoothed(x_filt, Xi_filt, Xi_pred, A, N, key):
    
    key, subkey = jrn.split(key)
    X_n = MVN(x_filt[-1], Xi_filt[-1]).sample(N, subkey)
    
    def sample_backwards(carry, inputs):
        X_smooth_next, key = carry
        x_filt, Xi_filt, Xi_pred, A = inputs

        G = Xi_filt @ jnp.linalg.solve(Xi_pred, A).T

        
        cond_expectation = x_filt + vmatmul(G, X_smooth_next - x_filt[None])
        cond_covariance = Xi_filt - G @ Xi_pred @ G.T

        key, subkey = jrn.split(key)
        new_samples = MVN(cond_expectation, cond_covariance).sample(seed=subkey)
        return (new_samples, key), new_samples
    
    key, subkey = jrn.split(key)
    _, X = scan(sample_backwards, (x_filt[None,-1], subkey), (x_filt[:-1], Xi_filt[:-1], Xi_pred[1:], A), reverse=True)
    
    return X.transpose((1,0,2))
