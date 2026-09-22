"""Binned (histogram) mutual information, Shannon entropy, and normalized MI.

The normalized quantity is the *uncertainty coefficient*

    U(A | B) = I(A; B) / H(A)

read as "the fraction of A's uncertainty explained by B". To keep the ratio
bounded in [0, 1], both the numerator I(A;B) and the denominator H(A) are
estimated from histograms (Shannon, nats) under a single self-consistent
binning rule (Freedman-Diaconis). This is deliberately distinct from the k-NN
``mutual_info_regression`` estimator used for the raw MI columns, which is
unbounded and reported in nats without normalization.

Known bias, measured on the 169 demo sites (2026-09-22). This estimator does
not return 0 for independent series: shuffling the second series and
recomputing gives a mean U of 0.081 against a mean reported U of 0.223, so
roughly a third of a typical value is estimator bias rather than dependence.
The bias grows as the record shortens (Spearman -0.72 between the shuffled
value and paired days), which means a map coloured by U is partly a map of
record length, and a seasonal slice inflates it further. Treat a value as an
upper bound, and compare only sites with records of similar length.

Correcting it means subtracting a permutation baseline (U minus the mean of
about 20 shuffles, reported with a p-value), or switching to equiprobable bins
with a fixed count per axis plus a Miller-Madow correction. Either change moves
published numbers, so it is a methods decision rather than a refactor.

Plain arrays in, plain floats out: nothing here knows about Django or the
dataset schema.
"""

from __future__ import annotations

import numpy as np

# Minimum paired daily observations before a value is reported (matches the
# raw-MI floor used by explorer.core.metrics).
MIN_PAIRED_DAYS = 30

# Guard rails on the Freedman-Diaconis bin count.
_MIN_BINS = 2
_MAX_BINS = 256


def _finite(x) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    return a[np.isfinite(a)]


def fd_bins(x) -> int:
    """Freedman-Diaconis bin count, with a Sturges fallback for degenerate data.

    FD bin width h = 2 * IQR / n**(1/3); n_bins = ceil((max - min) / h). When the
    IQR (or range) is zero -- e.g. a near-constant series -- fall back to Sturges
    ceil(log2 n + 1). Always returns an int in [_MIN_BINS, _MAX_BINS].
    """
    a = _finite(x)
    n = a.size
    if n < 2:
        return _MIN_BINS
    data_range = float(a.max() - a.min())
    if data_range <= 0:
        return _MIN_BINS
    q75, q25 = np.percentile(a, [75, 25])
    iqr = float(q75 - q25)
    if iqr > 0:
        h = 2.0 * iqr / (n ** (1.0 / 3.0))
        n_bins = int(np.ceil(data_range / h)) if h > 0 else 0
    else:
        n_bins = 0
    if n_bins < _MIN_BINS:  # Sturges fallback
        n_bins = int(np.ceil(np.log2(n) + 1))
    return int(np.clip(n_bins, _MIN_BINS, _MAX_BINS))


def hist_entropy(x) -> float:
    """Shannon entropy H(x) in nats from a Freedman-Diaconis histogram."""
    a = _finite(x)
    if a.size < 2:
        return float("nan")
    counts, _ = np.histogram(a, bins=fd_bins(a))
    total = counts.sum()
    if total == 0:
        return float("nan")
    p = counts[counts > 0] / total
    return float(-np.sum(p * np.log(p)))


def hist_mi(x, y) -> float:
    """Mutual information I(x;y) in nats from the joint 2-D histogram.

    Freedman-Diaconis bins per axis. Histogram MI is >= 0 up to rounding; the
    result is clamped at 0.
    """
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if a.size < 2:
        return float("nan")
    joint, _, _ = np.histogram2d(a, b, bins=[fd_bins(a), fd_bins(b)])
    total = joint.sum()
    if total == 0:
        return float("nan")
    p_xy = joint / total
    p_x = p_xy.sum(axis=1, keepdims=True)
    p_y = p_xy.sum(axis=0, keepdims=True)
    denom = p_x * p_y
    mask = (p_xy > 0) & (denom > 0)
    mi = float(np.sum(p_xy[mask] * np.log(p_xy[mask] / denom[mask])))
    return max(mi, 0.0)


def normalized_mi(x, y, *, min_paired_days: int = MIN_PAIRED_DAYS) -> tuple[float, float, float]:
    """Return (I(x;y), H(x), U) with U = I/H clipped to [0, 1].

    ``x`` is the reference variable whose entropy normalizes the MI.
    Returns NaNs when fewer than ``min_paired_days`` finite pairs or H(x) ~ 0.
    """
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if a.size < max(2, min_paired_days):
        return float("nan"), float("nan"), float("nan")
    h = hist_entropy(a)
    i = hist_mi(a, b)
    if not np.isfinite(h) or h <= 1e-12 or not np.isfinite(i):
        return i, h, float("nan")
    return i, h, float(np.clip(i / h, 0.0, 1.0))
