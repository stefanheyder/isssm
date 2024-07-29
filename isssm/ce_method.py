# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/45_cross_entropy_method.ipynb.

# %% auto 0
__all__ = ['vsolve_t', 'vmm', 'transition_precision_root', 'final_precision_root', 'ce_cholesky_block', 'ce_cholesky_last',
           'cholesky_components', 'simulate_backwards', 'simulate', 'marginals', 'log_prob', 'ce_log_weights',
           'joint_cov', 'forward_model_markov_process', 'ce_cholesky_precision']

# %% ../nbs/45_cross_entropy_method.ipynb 1
import jax.numpy as jnp
import jax.scipy as jsp
import jax.random as jrn
from .typing import MarkovProcessCholeskyComponents
from jax import vmap, jit
from .importance_sampling import ess_pct
from .pgssm import log_prob as log_prob_joint
import tensorflow_probability.substrates.jax.distributions as tfd
from jaxtyping import Float, Array, PRNGKeyArray
from typing import Tuple
from .importance_sampling import normalize_weights
from .util import converged
from jax.lax import while_loop, fori_loop, scan

# %% ../nbs/45_cross_entropy_method.ipynb 8
def transition_precision_root(cov):
    def _iter(carry, input):
        ei, = input
        i, cov = carry

        v = jnp.linalg.solve(cov, ei)
        # as jitting only works when shapes are constant
        # instead of submatrices with changing shapes, we replace
        # entries of cov succesively with identity matrix,
        # then, solving for ei is equvalent to soliving the i x i submatrix for e1
        cov = cov.at[:,i].set(ei).at[i,:].set(ei)
        return (i + 1, cov), v
    
    l, _ = cov.shape
    m = int(l/2)
    _, LT = scan(_iter, (0, cov), (jnp.eye(2 * m)[:m],))
    L = LT.T

    lam = jnp.sqrt(jnp.diag(L))
    L = L / lam[None]

    return L

def final_precision_root(cov):
    def _iter(carry, input):
        ei, = input
        i, cov = carry

        v = jnp.linalg.solve(cov, ei)
        # same trick as for transition_precision_root
        cov = cov.at[:,i].set(ei).at[i,:].set(ei)
        return (i + 1, cov), v
    
    m, _ = cov.shape
    _, LT = scan(_iter, (0, cov), (jnp.eye(m),))

    lam = jnp.sqrt(jnp.diag(LT))
    L = LT.T / lam[None]
    return L


def ce_cholesky_block(
    x: Float[Array, "N m"],  # samples of $X_t$
    x_next: Float[Array, "N m"],  # samples of $X_{t+1}$
    weights: Float[Array, "N"],  # $w$, need not be normalized
) -> Float[Array, "2*m m"]:  # Cholesky factor
    """Calculate the columns and section of rows of the Cholesky factor of $P$ corresponding to $X_t$, $t < n$."""

    joint_x = jnp.concatenate([x, x_next], axis=1)
    weights = weights / weights.sum()

    #joint_mean = jnp.sum(joint_x * weights[:, None], axis=0)
    #cov = jnp.atleast_2d(
    #    jnp.sum(
    #        (joint_x[:, :, None] @ joint_x[:, None, :]) * weights[:, None, None], axis=0
    #    )
    #    - joint_mean[:, None] @ joint_mean[None, :]
    #)
    cov = jnp.atleast_2d(jnp.cov(joint_x, aweights=weights, rowvar=False))

    return transition_precision_root(cov)


def ce_cholesky_last(
    x: Float[Array, "N m"],  # samples of $X_n$
    weights: Float[Array, "N"],  # $w$, need not be normalized
) -> Float[Array, "m m"]:  # Cholesky factor
    """Calculate the Cholesky factor of $P$ corresponding to $X_n$."""
    _, m = x.shape
    weights = weights / weights.sum()

    #mean = jnp.sum(x * weights[:, None], axis=0)

    #cov = jnp.atleast_2d(
    #    jnp.sum((x[:, :, None] @ x[:, None, :]) * weights[:, None, None])
    #    - mean @ mean.T
    #)
    cov = jnp.atleast_2d(jnp.cov(x, aweights=weights, rowvar=False))

    return final_precision_root(cov)


def cholesky_components(
    samples: Float[Array, "N n m"],  # samples of $X_1, \ldots, X_n$
    weights: Float[Array, "N"],  # $w$, need not be normalized
) -> MarkovProcessCholeskyComponents:  # block diagonal and off-diagonal components
    """calculate all components of the Cholesky factor of $P$"""
    current = samples[:, :-1]
    next = samples[:, 1:]

    diag, off_diag = jnp.split(
        vmap(ce_cholesky_block, (1, 1, None))(current, next, weights), 2, 1
    )
    last_diag = ce_cholesky_last(samples[:, -1], weights)
    full_diag = jnp.concatenate([diag, last_diag[None, :]], axis=0)

    return MarkovProcessCholeskyComponents(full_diag, off_diag)

# %% ../nbs/45_cross_entropy_method.ipynb 15
vsolve_t = vmap(jsp.linalg.solve_triangular, (None, 0))
vmm = vmap(jnp.matmul, (None, 0))

def simulate_backwards(z_t, x_next, diag_tt, off_diag_t_tp1):
    return jsp.linalg.solve_triangular(diag_tt.T, z_t - off_diag_t_tp1 @ x_next)


def simulate(
    full_diag: Float[Array, "n m m"],  # block diagonals of $L$
    off_diag: Float[Array, "n-1 m m"],  # off-diagonals of $L$
    key: PRNGKeyArray,  # random key
    N: int,  # number of samples
) -> Float[Array, "N n m"]:  # $N$ samples of $X_1, \ldots, X_n$
    """Simulate from Markov process with Cholesky factor $L$."""
    n, m, _ = full_diag.shape

    vsimulate_backwards = vmap(
        simulate_backwards,
        (0, 0, None, None)
    )

    def _iteration(carry, input):
        x, = carry
        z, full_diag, off_diag = input

        #new_x = vsolve_t(full_diag.T, z - vmm(off_diag, x))
        new_x = vsimulate_backwards(z, x, full_diag, off_diag)

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


# %% ../nbs/45_cross_entropy_method.ipynb 17
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

# %% ../nbs/45_cross_entropy_method.ipynb 20
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

# %% ../nbs/45_cross_entropy_method.ipynb 24
from .typing import PGSSM
def ce_log_weights(
    x: Float[Array, "n+1 m"], # the sample
    y: Float[Array, "n+1 p"], # the observations
    full_diag: Float[Array, "n+1 m m"],# block diagonals of $L$
    off_diag: Float[Array, "n m m"], # off-diagonals of $L$
    mean: Float[Array, "n+1 m"], # mean of the process
    model: PGSSM
) -> Float: # log-weights
    log_p = log_prob_joint(x, y, model)
    log_g = log_prob(x, full_diag, off_diag, mean)

    return log_p - log_g

# %% ../nbs/45_cross_entropy_method.ipynb 26
from jax.lax import cond
from .typing import GLSSM

from .kalman import kalman, smoother


def joint_cov(Xi_smooth_t, Xi_smooth_tp1, Xi_filt_t, Xi_pred_tp1, A_t):
    """Joint covariance of conditional Markov process"""
    off_diag = Xi_filt_t @ A_t.T @ jnp.linalg.solve(Xi_pred_tp1, Xi_smooth_tp1)
    return jnp.block([[Xi_smooth_t, off_diag], [off_diag.T, Xi_smooth_tp1]])


def forward_model_markov_process(y, model: GLSSM, time_reverse=True):
    """mean + Cholesky root components of precision matrix of smoothing distribution"""

    x0, A, *_ = model

    filtered = kalman(y, model)
    x_filter, Xi_filter, x_pred, Xi_pred = filtered
    x_smooth, Xi_smooth = smoother(filtered, A)

    (m,) = x0.shape

    # permute X_t and X_t+1
    P = jnp.block([[jnp.zeros((m, m)), jnp.eye(m)], [jnp.eye(m), jnp.zeros((m, m))]])

    covs = vmap(joint_cov)(
        Xi_smooth[:-1], Xi_smooth[1:], Xi_filter[:-1], Xi_pred[1:], A
    )

    def forwards(x_smooth, covs, Xi_smooth):
        return x_smooth[::-1], vmap(lambda cov: P @ cov @ P.T)(covs)[::-1], Xi_smooth[0]

    def backwards(x_smooth, covs, Xi_smooth):
        return x_smooth, covs, Xi_smooth[-1]

    mu, covs, final_cov = cond(
        time_reverse, backwards, forwards, x_smooth, covs, Xi_smooth
    )

    roots = vmap(transition_precision_root)(covs)

    root_diag, root_off_diag = jnp.split(roots, 2, 1)
    final_root = final_precision_root(final_cov)

    full_diag = jnp.concatenate([root_diag, final_root[None, :]], axis=0)

    return mu, (full_diag, root_off_diag)

# %% ../nbs/45_cross_entropy_method.ipynb 29
def ce_cholesky_precision(
    y: Float[Array, "n+1 p"],  # observations
    model: PGSSM, # the model
    initial_mean: Float[Array, "n+1 m"],  # initial mean
    initial_diag: Float[Array, "n+1 m m"],  # initial off_diag
    initial_off_diag: Float[Array, "n m m"],  # initial off_diag
    n_iter: int,  # number of iterations
    N: int,  # number of samples
    key: PRNGKeyArray,  # random key
    eps: Float = 1e-5,  # convergence threshold
):
    key, subkey = jrn.split(key)
    x0, A, Sigma, B, dist, xi = model

    def _break(val):
        i, diag, off_diag, mean, old_diag, old_off_diag, old_mean = val

        diag_converged = converged(diag, old_diag, eps)
        off_diag_converged = converged(off_diag, old_off_diag, eps)
        mean_converged = converged(mean, old_mean, eps)

        all_converged = jnp.logical_and(
                diag_converged, jnp.logical_and(off_diag_converged, mean_converged)
        )

        is_first_iteration = i == 0
        iteration_limit_reached = i >= n_iter

        return jnp.logical_and(
            jnp.logical_not(is_first_iteration),
            jnp.logical_or(
                all_converged,
                iteration_limit_reached,
            )
        )
    

    def _iteration(val):
        i, diag, off_diag, mean, _, _, _ = val

        samples = simulate(diag, off_diag, subkey, N) + mean

        log_weights = vmap(ce_log_weights, (0, *(None,) * 5))(
            samples, y, diag, off_diag, mean, model
        )

        weights = normalize_weights(log_weights)
        new_diag, new_off_diag = cholesky_components(samples, weights)
        new_mean = jnp.sum(samples * weights[:, None, None], axis=0)

        return i + 1, new_diag, new_off_diag, new_mean, diag, off_diag, mean

    init = _iteration(
        (0, initial_diag, initial_off_diag, initial_mean, initial_diag, initial_off_diag, initial_mean)
    )

    _keep_going = lambda x: jnp.logical_not(_break(x))
    iterations, diag, off_diag, mean, *_ = while_loop(_keep_going, _iteration, init)

    samples = simulate(diag, off_diag, subkey, N) + mean

    log_weights = vmap(ce_log_weights, (0, *(None,) * 5))(
        samples, y, diag, off_diag, mean, model
    )

    return (diag, off_diag, mean), (samples, log_weights), iterations
