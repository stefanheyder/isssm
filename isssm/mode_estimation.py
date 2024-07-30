# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/30_mode_estimation.ipynb.

# %% auto 0
__all__ = ['vmm', 'vdiag', 'vvmap', 'SmoothState', 'PseudoObs', 'PseudoObsCov', 'mode_estimation']

# %% ../nbs/30_mode_estimation.ipynb 5
from functools import partial

import jax.numpy as jnp
import jax.random as jrn
from jax import grad, jacfwd, jacrev, jit, vmap
from jax.lax import scan, while_loop
from jaxtyping import Array, Float

from .kalman import kalman, smoother
from .pgssm import simulate_lcssm
from .util import converged
from .typing import GLSSM, PGSSM, InitialState

# %% ../nbs/30_mode_estimation.ipynb 7
from .kalman import smoothed_signals
vmm = jit(vmap(jnp.matmul))
vdiag = jit(vmap(jnp.diag))
vvmap = lambda fun: vmap(vmap(fun))

SmoothState = Float[Array, "n+1 m"]
PseudoObs = Float[Array, "n+1 p"]
PseudoObsCov = Float[Array, "n+1 p p"]


def mode_estimation(
    y: Float[Array, "n+1 p"],  # observation
    model: PGSSM,
    s_init: Float[Array, "n+1 p"],  # initial signal
    n_iter: int,  # number of iterations
    log_lik=None,  # log likelihood function
    d_log_lik=None,  # derivative of log likelihood function
    dd_log_lik=None,  # second derivative of log likelihood function
    eps: Float = 1e-5,  # precision of iterations
) -> tuple[SmoothState, PseudoObs, PseudoObsCov]:
    x0, A, Sigma, B, dist, xi = model

    def default_log_lik(s_ti, xi_ti, y_ti):
        return dist(s_ti, xi_ti).log_prob(y_ti).sum()

    if log_lik is None:
        log_lik = default_log_lik

    if d_log_lik is None:
        d_log_lik = jacfwd(log_lik, argnums=0)
    if dd_log_lik is None:
        dd_log_lik = jacrev(d_log_lik, argnums=0)

    vd_log_lik = jit(vvmap(d_log_lik))
    vdd_log_lik = jit(vvmap(dd_log_lik))

    def _break(val):
        _, i, z, Omega, z_old, Omega_old = val

        z_converged = converged(z, z_old, eps)
        Omega_converged = converged(Omega, Omega_old, eps)
        iteration_limit_reached = i >= n_iter

        return jnp.logical_or(
            jnp.logical_and(z_converged, Omega_converged), iteration_limit_reached
        )

    def _iteration(val):
        s, i, z_old, Omega_old, _, _ = val

        grad = vd_log_lik(s, xi, y)
        Gamma = -vdd_log_lik(s, xi, y)
        # assume hessian is diagonal
        Omega = vdiag(1.0 / Gamma)

        z = s + grad / Gamma
        approx_glssm = GLSSM(x0, A, Sigma, B, Omega)

        filtered = kalman(z, approx_glssm)
        s_new = smoothed_signals(filtered, z, approx_glssm)

        return s_new, i + 1, z, Omega, z_old, Omega_old

    init = _iteration((s_init, 0, None, None, None, None))
    # iterate once more, so z_old, Omega_old have sensible values
    init = _iteration(init)

    s, n_iters, z, Omega,  _, _ = while_loop(_break, _iteration, init)

    approx_glssm = GLSSM(x0, A, Sigma, B, Omega)
    x_smooth, _  = smoother(kalman(z, approx_glssm), A)
    return x_smooth, z, Omega
