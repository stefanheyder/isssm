"""See also the corresponding [section in my thesis](https://stefanheyder.github.io/dissertation/thesis.pdf#nameddest=section.3.2)"""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/10_kalman_filter_smoother.ipynb.

# %% auto 0
__all__ = ['State', 'StateCov', 'StateTransition', 'kalman', 'smoother', 'account_for_nans', 'filter_intervals',
           'smoother_intervals', 'FFBS', 'disturbance_smoother', 'smoothed_signals', 'simulation_smoother',
           'to_signal_model', 'state_conditional_on_signal', 'state_mode']

# %% ../nbs/10_kalman_filter_smoother.ipynb 1
import jax.numpy as jnp
import jax.random as jrn
import jax.scipy.linalg as jsla
import tensorflow_probability.substrates.jax.distributions as tfd
from jax import vmap, jit
from jax.lax import scan
from jaxtyping import Array, Float, PRNGKeyArray

from .typing import GLSSM, FilterResult, Observations, SmootherResult
from .util import MVN_degenerate as MVN, mm_sim

# %% ../nbs/10_kalman_filter_smoother.ipynb 7
from .util import append_to_front


def _predict(
    x_filt: Float[Array, "m"],  # $X_{t|t}$
    Xi_filt: Float[Array, "m m"],  # $\Xi_{t|t}
    u: Float[Array, "m"],  # $u_{t + 1}$
    A: Float[Array, "m m"],  # $A_t$
    Sigma: Float[Array, "l l"],  # $\Sigma_{t + 1}
    D: Float[Array, "m l"],
):
    """perform a single prediction step"""
    x_pred = A @ x_filt + u
    Xi_pred = A @ Xi_filt @ A.T + D @ Sigma @ D.T

    return x_pred, Xi_pred


def _filter(
    x_pred: Float[Array, "m"],
    Xi_pred: Float[Array, "m m"],
    y: Float[Array, "p"],
    v: Float[Array, "p"],
    B: Float[Array, "p m"],
    Omega: Float[Array, "p p"],
):
    """perform a single filtering step"""
    y_pred = v + B @ x_pred
    Psi_pred = B @ Xi_pred @ B.T + Omega
    K = (
        Xi_pred @ B.T @ jnp.linalg.pinv(Psi_pred, hermitian=True)
    )  # jsla.solve(Psi_pred, B).T
    x_filt = x_pred + K @ (y - y_pred)
    Xi_filt = Xi_pred - K @ Psi_pred @ K.T

    return x_filt, Xi_filt


def kalman(
    y: Observations,  # observatoins
    glssm: GLSSM,  # model
) -> FilterResult:  # filtered & predicted states and covariances
    """Perform the Kalman filter"""
    u, A, D, Sigma0, Sigma, v, B, Omega = glssm
    np1, p, m = B.shape
    _, m, l = D.shape

    def step(carry, inputs):
        x_filt, Xi_filt = carry
        y, u, A, D, Sigma, v, B, Omega = inputs

        x_pred, Xi_pred = _predict(x_filt, Xi_filt, u, A, Sigma, D)
        x_filt_next, Xi_filt_next = _filter(x_pred, Xi_pred, y, v, B, Omega)

        return (x_filt_next, Xi_filt_next), (x_filt_next, Xi_filt_next, x_pred, Xi_pred)

    # artificial state X_{-1} with mean x_0
    # covariance Sigma_0, transition identity and innovation cov 0
    # will lead to X_0 having correct predictive distribution
    # this avoids having to compute a separate filtering step beforehand

    A_ext = append_to_front(jnp.eye(m), A)
    Sigma_ext = append_to_front(jnp.zeros((l, l)), Sigma)
    D_ext = append_to_front(jnp.zeros((m, l)), D)
    u_ext = append_to_front(jnp.zeros(m), u[1:])

    init = (u[0], Sigma0)

    _, (x_filt, Xi_filt, x_pred, Xi_pred) = scan(
        step, init, (y, u_ext, A_ext, D_ext, Sigma_ext, v, B, Omega)
    )

    return FilterResult(x_filt, Xi_filt, x_pred, Xi_pred)

# %% ../nbs/10_kalman_filter_smoother.ipynb 13
State = Float[Array, "m"]
StateCov = Float[Array, "m m"]
StateTransition = Float[Array, "m m"]


def _smooth_step(
    x_filt: State,
    x_pred_next: State,
    x_smooth_next: State,
    Xi_filt: StateCov,
    Xi_pred_next: StateCov,
    Xi_smooth_next: StateCov,
    A: StateTransition,
):
    err = x_smooth_next - x_pred_next
    Gain = Xi_filt @ A.T @ jnp.linalg.pinv(Xi_pred_next, hermitian=True)

    x_smooth = x_filt + Gain @ err
    Xi_smooth = Xi_filt - Gain @ (Xi_pred_next - Xi_smooth_next) @ Gain.T

    return (x_smooth, Xi_smooth)


def smoother(
    filter_result: FilterResult, A: Float[Array, "n m m"]  # transition matrices
) -> SmootherResult:
    """perform the Kalman smoother"""
    x_filt, Xi_filt, x_pred, Xi_pred = filter_result

    def step(carry, inputs):
        x_smooth_next, Xi_smooth_next = carry
        x_filt, Xi_filt, x_pred_next, Xi_pred_next, A = inputs

        x_smooth, Xi_smooth = _smooth_step(
            x_filt, x_pred_next, x_smooth_next, Xi_filt, Xi_pred_next, Xi_smooth_next, A
        )

        return (x_smooth, Xi_smooth), (x_smooth, Xi_smooth)

    _, (x_smooth, Xi_smooth) = scan(
        step,
        (x_filt[-1], Xi_filt[-1]),
        (x_filt[:-1], Xi_filt[:-1], x_pred[1:], Xi_pred[1:], A),
        reverse=True,
    )

    x_smooth = jnp.concatenate([x_smooth, x_filt[None, -1]])
    Xi_smooth = jnp.concatenate([Xi_smooth, Xi_filt[None, -1]])

    return SmootherResult(x_smooth, Xi_smooth)

# %% ../nbs/10_kalman_filter_smoother.ipynb 18
# y not jittable: boolean indices have to be concrete
def account_for_nans(model: GLSSM, y: Observations) -> tuple[GLSSM, Observations]:
    u, A, D, Sigma0, Sigma, v, B, Omega = model

    missing_indices = jnp.isnan(y)

    y = jnp.nan_to_num(y, nan=0.0)

    v = v.at[missing_indices].set(0.0)
    B = B.at[missing_indices].set(0.0)
    # set rows and columns of Omega to 0.
    Omega = Omega.at[missing_indices].set(0.0)
    Omega = Omega.transpose((0, 2, 1)).at[missing_indices].set(0.0)

    return GLSSM(u, A, D, Sigma0, Sigma, v, B, Omega), y

# %% ../nbs/10_kalman_filter_smoother.ipynb 22
from tensorflow_probability.substrates.jax.distributions import Normal


def filter_intervals(
    result: FilterResult, alpha: Float = 0.05
) -> Float[Array, "2 n+1 m"]:
    x_filt, Xi_filt, *_ = result
    marginal_variances = vmap(jnp.diag)(Xi_filt)
    dist = Normal(x_filt, marginal_variances)
    lower = dist.quantile(alpha / 2)
    upper = dist.quantile(1 - alpha / 2)

    return jnp.concatenate((lower[None], upper[None]))


def smoother_intervals(
    result: SmootherResult, alpha: Float = 0.05
) -> Float[Array, "2 n+1 m"]:
    x_smooth, Xi_smooth = result
    marginal_variances = vmap(jnp.diag)(Xi_smooth)
    dist = Normal(x_smooth, marginal_variances)
    lower = dist.quantile(alpha / 2)
    upper = dist.quantile(1 - alpha / 2)

    return jnp.concatenate((lower[None], upper[None]))

# %% ../nbs/10_kalman_filter_smoother.ipynb 25
def _simulate_smoothed_FW1994(
    x_filt: Float[Array, "n+1 m"],
    Xi_filt: Float[Array, "n+1 m m"],
    Xi_pred: Float[Array, "n+1 m m"],
    A: Float[Array, "n m m"],
    N: int,  # number of samples
    key: PRNGKeyArray,  # the random states
) -> Float[Array, "N n+1 m"]:  # array of N samples from the smoothing distribution
    r"""Simulate from smoothing distribution $p(X_0, \dots, X_n|Y_0, \dots, Y_n)$"""

    key, subkey = jrn.split(key)
    X_n = MVN(x_filt[-1], Xi_filt[-1]).sample(N, subkey)

    def sample_backwards(carry, inputs):
        X_smooth_next, key = carry
        x_filt, Xi_filt, Xi_pred, A = inputs

        G = Xi_filt @ jnp.linalg.solve(Xi_pred, A).T

        cond_expectation = x_filt + mm_sim(G, X_smooth_next - (A @ x_filt)[None])
        cond_covariance = Xi_filt - G @ Xi_pred @ G.T

        key, subkey = jrn.split(key)
        new_samples = MVN(cond_expectation, cond_covariance).sample(seed=subkey)
        return (new_samples, key), new_samples

    key, subkey = jrn.split(key)
    _, X = scan(
        sample_backwards,
        (X_n, subkey),
        (x_filt[:-1], Xi_filt[:-1], Xi_pred[1:], A),
        reverse=True,
    )

    X_full = jnp.concatenate((X, X_n[None]))

    return X_full.transpose((1, 0, 2))


def FFBS(
    y: Observations,  # Observations $y$
    model: GLSSM,  # GLSSM
    N: int,  # number of samples
    key: PRNGKeyArray,  # random state
) -> Float[Array, "N n+1 m"]:  # N samples from the smoothing distribution
    r"""The Forward-Filter Backwards-Sampling Algorithm from [@Fruhwirth-Schnatter1994Data]."""
    x_filt, Xi_filt, _, Xi_pred = kalman(y, model)

    key, subkey = jrn.split(key)
    return _simulate_smoothed_FW1994(x_filt, Xi_filt, Xi_pred, model.A, N, subkey)

# %% ../nbs/10_kalman_filter_smoother.ipynb 30
from .util import mm_time


def disturbance_smoother(
    filtered: FilterResult,  # filter result
    y: Observations,  # observations
    model: GLSSM,  # model
) -> Float[Array, "n+1 p"]:  # smoothed disturbances
    """perform the disturbance smoother for observation disturbances only"""
    x_filt, Xi_filt, x_pred, Xi_pred = filtered
    u, A, D, Sigma0, Sigma, v, B, Omega = model
    np1, p, m = B.shape

    def step(carry, inputs):
        (r,) = carry
        O_Pinv_y, O_KT_AT, BT_Pinv_y, L = inputs

        eta_smooth = O_Pinv_y - O_KT_AT @ r
        r_prev = BT_Pinv_y + L.T @ r

        return (r_prev,), eta_smooth

    A_ext = jnp.concatenate((A, jnp.eye(m)[jnp.newaxis]), axis=0)
    BT = B.transpose((0, 2, 1))

    # offline computation is faster
    y_tilde = y - mm_time(B, x_pred)
    Psi_pred = B @ Xi_pred @ BT + Omega
    Psi_pred_pinv = jnp.linalg.pinv(Psi_pred, hermitian=True)
    O_Pinv_y = mm_time(Omega @ Psi_pred_pinv, y_tilde)
    K = Xi_pred @ BT @ Psi_pred_pinv

    KT = K.transpose((0, 2, 1))
    AT = A_ext.transpose((0, 2, 1))
    O_KT_AT = Omega @ KT @ AT
    BT_Pinv_y = mm_time(BT @ Psi_pred_pinv, y_tilde)

    L = A_ext @ (jnp.eye(m)[None] - K @ B)

    _, eta_smooth = scan(
        step, (jnp.zeros(m),), (O_Pinv_y, O_KT_AT, BT_Pinv_y, L), reverse=True
    )

    return eta_smooth


def smoothed_signals(
    filtered: FilterResult,  # filter result
    y: Observations,  # observations
    model: GLSSM,  # model
) -> Float[Array, "n+1 m"]:  # smoothed signals
    """compute smoothed signals from filter result"""
    eta_smooth = disturbance_smoother(filtered, y, model)
    return y - eta_smooth

# %% ../nbs/10_kalman_filter_smoother.ipynb 35
from tensorflow_probability.substrates.jax.distributions import Chi2
from .util import degenerate_cholesky
from .util import location_antithetic, scale_antithethic


def _sim_from_innovations_disturbances(
    model: GLSSM,
    x0: Float[Array, "N m"],
    eps: Float[Array, "N n l"],
    eta: Float[Array, "N n+1 p"],
) -> Float[Array, "N n+1 p"]:
    u, A, D, Sigma0, Sigma, v, B, Omega = model
    N, np1, l = eps.shape
    n, m, l = D.shape

    def step(carry, inputs):
        (x,) = carry
        u, A, D, eps, v, B, eta = inputs

        x_next = u + (A @ x[..., None])[..., 0] + mm_sim(D, eps)
        y_next = v + (B @ x[..., None])[..., 0] + eta

        return (x_next,), y_next

    A_ext = append_to_front(jnp.eye(m), A)
    u_ext = append_to_front(jnp.zeros(m), u[1:])
    D_ext = append_to_front(jnp.zeros((m, l)), D)
    eps_ext = append_to_front(jnp.zeros((N, l)), eps.transpose((1, 0, 2)))

    initial = (x0,)  # initial state
    (x,), y = scan(
        step,
        initial,
        (u_ext, A_ext, D_ext, eps_ext, v, B, eta.transpose(1, 0, 2)),
    )

    return y.transpose((1, 0, 2))


def simulation_smoother(
    model: GLSSM,  # model
    y: Observations,  # observations
    N: int,  # number of samples to draw
    key: PRNGKeyArray,  # random number seed
) -> Float[Array, "N n+1 m"]:  # N samples from the smoothing distribution of signals
    """Simulate from the smoothing distribution of signals"""
    np1, p, m = model.B.shape
    n, _, l = model.D.shape

    @jit
    def signal_filter_smoother(y, model):
        return smoothed_signals(kalman(y, model), y, model)

    key, subkey = jrn.split(key)
    u_x0 = MVN(jnp.zeros(m), jnp.eye(m)).sample(N, subkey)
    chol_Sigma0 = degenerate_cholesky(model.Sigma0)
    x0 = mm_sim(chol_Sigma0, u_x0)

    key, subkey = jrn.split(key)
    u_eps = MVN(jnp.zeros((n, l)), jnp.eye(l)[None]).sample(N, subkey)
    chol_Sigma = degenerate_cholesky(model.Sigma)
    eps = vmap(vmap(jnp.matmul), (None, 0))(chol_Sigma, u_eps)

    key, subkey = jrn.split(key)
    u_eta = MVN(jnp.zeros((np1, p)), jnp.eye(p)[None]).sample(N, subkey)
    chol_Omega = degenerate_cholesky(model.Omega)
    eta = vmap(vmap(jnp.matmul), (None, 0))(chol_Omega, u_eta)

    y_sim = _sim_from_innovations_disturbances(model, x0, eps, eta)

    signals_smooth = signal_filter_smoother(y, model)
    sim_signals = y_sim - eta
    sim_signals_smooth = vmap(signal_filter_smoother, (0, None))(y_sim, model)

    samples = signals_smooth[None] + (sim_signals - sim_signals_smooth)

    # u = jnp.concatenate((u_x0[:, None, :], u_eps, u_eta), axis=-1)
    u = jnp.concatenate(
        (u_x0.reshape((N, -1)), u_eps.reshape((N, -1)), u_eta.reshape((N, -1))), axis=1
    )

    l_samples = location_antithetic(samples, signals_smooth)
    s_samples = scale_antithethic(u, samples, signals_smooth)
    ls_samples = scale_antithethic(u, l_samples, signals_smooth)

    full_samples = jnp.concatenate((samples, l_samples, s_samples, ls_samples), axis=0)

    return full_samples

# %% ../nbs/10_kalman_filter_smoother.ipynb 39
from .typing import PGSSM


def to_signal_model(model: GLSSM | PGSSM):
    np1, p, _ = model.B.shape
    return GLSSM(
        model.u,
        model.A,
        model.D,
        model.Sigma0,
        model.Sigma,
        model.v,
        model.B,
        jnp.zeros((np1, p, p)),
    )


def state_conditional_on_signal(
    model: GLSSM | PGSSM, signal_mode: Float[Array, "n+1 p"]
):
    signal_model = to_signal_model(model)
    return smoother(kalman(signal_mode, signal_model), signal_model.A)


def state_mode(model: GLSSM | PGSSM, signal_mode: Float[Array, "n+1 p"]):
    return state_conditional_on_signal(model, signal_mode).x_smooth
