# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/45_cross_entropy_method.ipynb.

# %% auto 0
__all__ = ['vsolve_t', 'vmm', 'ce_cholesky_block', 'ce_cholesky_last', 'cholesky_components', 'simulate', 'marginals', 'log_prob',
           'ce_log_weights', 'ce_cholesky_precision']

# %% ../nbs/45_cross_entropy_method.ipynb 1
import jax.numpy as jnp
import jax.scipy as jsp
import jax.random as jrn
from jax import vmap, jit
from .importance_sampling import ess_pct
from .lcssm import log_prob as log_prob_joint
import tensorflow_probability.substrates.jax.distributions as tfd
from jaxtyping import Float, Array, PRNGKeyArray
from typing import Tuple
from .importance_sampling import normalize_weights
from .optim import converged
from jax.lax import while_loop, fori_loop, scan

# %% ../nbs/45_cross_entropy_method.ipynb 9
def ce_cholesky_block(
    x: Float[Array, "N m"],  # samples of $X_t$
    x_next: Float[Array, "N m"],  # samples of $X_{t+1}$
    weights: Float[Array, "N"],  # $w$, need not be normalized
) -> Float[Array, "2*m m"]:  # Cholesky factor
    """Calculate the columns and section of rows of the Cholesky factor of $P$ corresponding to $X_t$, $t < n$."""
    _, m = x.shape
    joint_x = jnp.concatenate([x, x_next], axis=1)
    weights = weights / weights.sum()

    joint_mean = jnp.sum(joint_x * weights[:, None], axis=0)
    cov = jnp.atleast_2d(
        jnp.sum(
            (joint_x[:, :, None] @ joint_x[:, None, :]) * weights[:, None, None], axis=0
        )
        - joint_mean[:, None] @ joint_mean[None, :]
    )

#    L = jnp.zeros((2 * m, m))
#    for i in range(m):
#        # todo rewrite to: replace i-th row and column by correct unit vector
#        # makes it jaxable
#        ei = jnp.eye(2 * m)[i]
#        v = jnp.linalg.solve(cov, ei)
#        cov = cov.at[:,i].set(ei).at[i,:].set(ei)
#        L = L.at[:,i].set(v)
#
#        #sub_cov = cov[i:, i:]
#        #v = jnp.linalg.solve(sub_cov, jnp.eye(2 * m - i)[0])
#        #lam = jnp.sqrt(v[0])
#        #L = L.at[i:, i].set(v / lam)
#
    def _iter(carry, input):
        ei, = input
        i, cov = carry

        v = jnp.linalg.solve(cov, ei)
        cov = cov.at[:,i].set(ei).at[i,:].set(ei)
        return (i + 1, cov), v
    
    _, LT = scan(_iter, (0, cov), (jnp.eye(2 * m)[:m],))
    L = LT.T

    lam = jnp.sqrt(jnp.diag(L))
    L = L / lam[:, None]

    return L


def ce_cholesky_last(
    x: Float[Array, "N m"],  # samples of $X_n$
    weights: Float[Array, "N"],  # $w$, need not be normalized
) -> Float[Array, "m m"]:  # Cholesky factor
    """Calculate the Cholesky factor of $P$ corresponding to $X_n$."""
    _, m = x.shape
    weights = weights / weights.sum()

    mean = jnp.sum(x * weights[:, None], axis=0)

    cov = jnp.atleast_2d(
        jnp.sum((x[:, :, None] @ x[:, None, :]) * weights[:, None, None])
        - mean @ mean.T
    )

    
    #for i in range(m):
    #    ei = jnp.eye(m)[i]
    #    v = jnp.linalg.solve(cov, ei)
    #    L = L.at[:,i].set(v)
    #    cov = cov.at[:,i].set(ei).at[i,:].set(ei)

    #    #sub_cov = cov[i:, i:]
    #    #v = jnp.linalg.solve(sub_cov, jnp.eye(m - i)[0])
    #    #lam = jnp.sqrt(v[0])
    #    #L = L.at[i:, i].set(v / lam)
        
    def _iter(carry, input):
        ei, = input
        i, cov = carry

        v = jnp.linalg.solve(cov, ei)
        cov = cov.at[:,i].set(ei).at[i,:].set(ei)
        return (i + 1, cov), v
    
    _, LT = scan(_iter, (0, cov), (jnp.eye(m),))

    lam = jnp.sqrt(jnp.diag(LT))
    L = LT.T / lam[:, None]
    return L


def cholesky_components(
    samples: Float[Array, "N n m"],  # samples of $X_1, \ldots, X_n$
    weights: Float[Array, "N"],  # $w$, need not be normalized
) -> Tuple[
    Float[Array, "n m m"], Float[Array, "n m m"]
]:  # block diagonal and off-diagonal components
    """calculate all components of the Cholesky factor of $P$"""
    current = samples[:, :-1]
    next = samples[:, 1:]

    diag, off_diag = jnp.split(
        vmap(ce_cholesky_block, (1, 1, None))(current, next, weights), 2, 1
    )
    last_diag = ce_cholesky_last(samples[:, -1], weights)
    full_diag = jnp.concatenate([diag, last_diag[None, :]], axis=0)

    return full_diag, off_diag

# %% ../nbs/45_cross_entropy_method.ipynb 16
vsolve_t = vmap(jsp.linalg.solve_triangular, (None, 0))
vmm = vmap(jnp.matmul, (None, 0))


def simulate(
    full_diag: Float[Array, "n m m"],  # block diagonals of $L$
    off_diag: Float[Array, "n-1 m m"],  # off-diagonals of $L$
    key: PRNGKeyArray,  # random key
    N: int,  # number of samples
) -> Float[Array, "N n m"]:  # $N$ samples of $X_1, \ldots, X_n$
    """Simulate from Markov process with Cholesky factor $L$."""
    n, m, _ = full_diag.shape

    #key, subkey = jrn.split(key)
    #x = jnp.zeros((N, n, m))
    #z_n = jrn.normal(subkey, shape=(N, m))
    #x_n = vsolve_t(full_diag[-1].T, z_n)

    #x = x.at[:, -1].set(x_n)

    #for i in range(n - 1):
    #    key, subkey = jrn.split(key)
    #    z = jrn.normal(subkey, shape=(N, m))
    #    new_x = vsolve_t(
    #        full_diag[n - i - 2].T, z - vmm(off_diag[n - i - 2], x[:, n - i - 1])
    #    )
    #    x = x.at[:, n - i - 2].set(new_x)

    def _iteration(carry, input):
        x, = carry
        z, full_diag, off_diag = input

        new_x = vsolve_t(full_diag.T, z - vmm(off_diag, x))

        return (new_x,), new_x
    
    key, subkey = jrn.split(key)
    extended_off_diag = jnp.concatenate([off_diag, jnp.zeros((1, m, m))], axis=0)
    _, x = scan(
        _iteration, 
        (jnp.zeros((N,m)),), 
        (jrn.normal(subkey, shape=(n, N, m)), full_diag[::-1], extended_off_diag[::-1])
    )

    x = x[::-1].transpose((1, 0, 2))

    return x


# %% ../nbs/45_cross_entropy_method.ipynb 18
def marginals(
    mu: Float[Array, "m"],  # mean
    full_diag: Float[Array, "n m m"],  # block diagonals of $L$
    off_diag: Float[Array, "n-1 m m"],  # off-diagonals of $L$
):
    n, m, _ = full_diag.shape

    Sigma = jnp.zeros((n, m, m))
    P_n = full_diag[-1].T @ full_diag[-1]
    Sigma = Sigma.at[-1].set(jnp.linalg.inv(P_n))

    for i in reversed(range(n - 1)):
        A_i = - jsp.linalg.solve_triangular(full_diag[i].T, off_diag[i].T)
        Omega_i = jnp.linalg.inv(full_diag[i].T @ full_diag[i])

        Sigma = Sigma.at[i].set(A_i.T @ Sigma[i + 1] @ A_i + Omega_i)

    return mu, vmap(jnp.diag)(Sigma)

# %% ../nbs/45_cross_entropy_method.ipynb 21
def log_prob(
    x: Float[Array, "n+1 m"], # the location at which to evaluate the likelihood
    full_diag: Float[Array, "n+1 m m"],# block diagonals of $L$
    off_diag: Float[Array, "n m m"], # off-diagonals of $L$
    mean: Float[Array, "n+1 m"], # mean of the process
) -> Float: # log-likelihood
    np1, m = x.shape

    # append zeros to have the same shape as full_diag
    extended_off_diag = jnp.concatenate([off_diag, jnp.zeros((m, m))[None]], axis=0)
    centered = x - mean

    # L is triangular
    logdet = 2 * jnp.sum(jnp.log(vmap(jnp.diag)(full_diag)))

    # exploit sparsity of L
    extended_centered = jnp.concatenate([centered, jnp.zeros((1, m))], axis=0)
    Lt_x = (
        full_diag.transpose((0, 2, 1)) @ extended_centered[:-1,:,None]
        + extended_off_diag.transpose((0, 2, 1)) @ extended_centered[1:,:,None]
    )[:,:,0]
    l2_norm = jnp.sum(Lt_x ** 2)

    return -np1 * m / 2 * jnp.log(2 * jnp.pi) - 1 / 2 * logdet - 1 / 2 * l2_norm

# %% ../nbs/45_cross_entropy_method.ipynb 28
def ce_log_weights(
    x: Float[Array, "n+1 m"], # the sample
    y: Float[Array, "n+1 p"], # the observations
    full_diag: Float[Array, "n+1 m m"],# block diagonals of $L$
    off_diag: Float[Array, "n m m"], # off-diagonals of $L$
    mean: Float[Array, "n+1 m"], # mean of the process
    x0: Float[Array, "m"], # initial state
    A: Float[Array, "n m m"], # transition matrix
    Sigma: Float[Array, "n+1 m m"], # covariance matrix
    B: Float[Array, "n+1 p m"], # observation matrix
    dist: tfd.Distribution, # distribution of the initial state
    xi: Float[Array, "n+1 m"], # initial state
) -> Float: # log-weights
    log_p = log_prob_joint(x, y, x0, A, Sigma, B, dist, xi)
    log_g = log_prob(x, full_diag, off_diag, mean)

    return log_p - log_g

# %% ../nbs/45_cross_entropy_method.ipynb 29
def ce_cholesky_precision(
    y: Float[Array, "n+1 p"],  # observations
    x0: Float[Array, "m"],  # initial state
    A: Float[Array, "n m m"],  # state transition matrices
    Sigma: Float[Array, "n+1 m m"],  # state noise covariance matrices
    B: Float[Array, "n+1 p m"],  # observation matrices
    xi: Float[Array, "n+1 p"],  # observation parameters
    dist,  # observation distribution
    initial_samples: Float[Array, "N n m"],  # initial samples
    initial_log_weights: Float[Array, "N"],  # initial weights
    n_iter: int,  # number of iterations
    N: int,  # number of samples
    key: PRNGKeyArray,  # random key
    eps: Float = 1e-5,  # convergence threshold
):
    key, subkey = jrn.split(key)

    def _break(val):
        i, diag, off_diag, mean, old_diag, old_off_diag, old_mean = val

        diag_converged = converged(diag, old_diag, eps)
        off_diag_converged = converged(off_diag, old_off_diag, eps)
        mean_converged = converged(mean, old_mean, eps)

        iteration_limit_reached = i >= n_iter

        return jnp.logical_or(
            jnp.logical_and(
                diag_converged, jnp.logical_and(off_diag_converged, mean_converged)
            ),
            iteration_limit_reached,
        )

    def _iteration(val):
        i, diag, off_diag, mean, _, _, _ = val

        samples = simulate(diag, off_diag, subkey, N) + mean

        log_weights = vmap(ce_log_weights, (0, *(None,) * 10))(
            samples, y, diag, off_diag, mean, x0, A, Sigma, B, dist, xi
        )

        weights = normalize_weights(log_weights)
        new_diag, new_off_diag = cholesky_components(samples, weights)
        new_mean = jnp.sum(samples * weights[:, None, None], axis=0)

        return i + 1, new_diag, new_off_diag, new_mean, diag, off_diag, mean

    initial_weights = normalize_weights(initial_log_weights)
    initial_diag, initial_off_diag = cholesky_components(
        initial_samples, initial_weights
    )
    initial_mean = jnp.sum(initial_samples * initial_weights[:, None, None], axis=0)

    init = _iteration(
        (0, initial_diag, initial_off_diag, initial_mean, None, None, None)
    )

    # cholesky helper functions not jittable
    _keep_going = lambda x: jnp.logical_not(_break(x))
    iterations, diag, off_diag, mean, *_ = while_loop(_keep_going, _iteration, init)
    #val = init
    #while(not _break(val)):
    #    val = _iteration(val)
    #iterations, diag, off_diag, mean, *_ = val

    samples = simulate(diag, off_diag, subkey, N) + mean

    log_weights = vmap(ce_log_weights, (0, *(None,) * 10))(
        samples, y, diag, off_diag, mean, x0, A, Sigma, B, dist, xi
    )

    return (diag, off_diag, mean), (samples, log_weights), iterations
