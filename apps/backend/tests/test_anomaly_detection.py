"""Unit tests for LiveBench's behavioral anomaly detectors.

Each detector is a pure function over signal_history buffers, so we feed
synthetic telemetry and assert on the returned Anomaly pattern types.
"""

from collections import deque

from src.live_bench import LiveBench


def bench_with(signals: dict) -> LiveBench:
    bench = LiveBench("test-project")
    for name, values in signals.items():
        bench.signal_history[name] = deque(values, maxlen=200)
    return bench


# ── Oscillation: motor sign-changes in a 2s window ────────────────────

def test_oscillation_detected_on_alternating_motor():
    bench = bench_with({"left_motor": [0.5, -0.5] * 10})
    anomalies = bench._analyze_oscillation()
    assert len(anomalies) == 1
    assert anomalies[0].pattern_type == "oscillation"
    assert anomalies[0].signal_name == "left_motor"


def test_no_oscillation_on_steady_motor():
    bench = bench_with({"left_motor": [0.5] * 20, "right_motor": [0.5] * 20})
    assert bench._analyze_oscillation() == []


def test_oscillation_ignores_near_zero_jitter():
    # Sign flips below the 0.05 hysteresis band are noise, not reversals
    bench = bench_with({"left_motor": [0.03, -0.03] * 10})
    assert bench._analyze_oscillation() == []


def test_oscillation_requires_minimum_samples():
    bench = bench_with({"left_motor": [0.5, -0.5, 0.5, -0.5]})
    assert bench._analyze_oscillation() == []


# ── Non-convergence: variance of pid_error / distance ─────────────────

def test_non_convergence_on_high_variance_pid_error():
    bench = bench_with({"pid_error": [0.0, 10.0] * 15})  # variance 25 > 5
    anomalies = bench._analyze_convergence()
    assert len(anomalies) == 1
    assert anomalies[0].pattern_type == "non_convergence"
    assert anomalies[0].signal_name == "pid_error"


def test_converged_pid_error_is_clean():
    bench = bench_with({"pid_error": [2.0] * 30})
    assert bench._analyze_convergence() == []


def test_non_convergence_requires_minimum_samples():
    bench = bench_with({"pid_error": [0.0, 10.0] * 4})  # only 8 samples
    assert bench._analyze_convergence() == []


# ── Anti-correlation: Pearson r between left/right motors ─────────────

def test_anti_correlated_motors_detected():
    left = [0.2, 0.4, 0.6, 0.8, 1.0] * 4
    right = [-v for v in left]  # r = -1
    bench = bench_with({"left_motor": left, "right_motor": right})
    anomalies = bench._analyze_correlation()
    assert len(anomalies) == 1
    assert anomalies[0].pattern_type == "anti_correlation"


def test_correlated_motors_are_clean():
    left = [0.2, 0.4, 0.6, 0.8, 1.0] * 4
    bench = bench_with({"left_motor": left, "right_motor": list(left)})
    assert bench._analyze_correlation() == []


def test_constant_motors_skip_correlation():
    # Zero variance would divide by zero; the detector must guard it
    bench = bench_with({"left_motor": [0.5] * 20, "right_motor": [0.5] * 20})
    assert bench._analyze_correlation() == []


# ── Energy waste: mean |motor| utilization ────────────────────────────

def test_over_energy_on_saturated_motors():
    bench = bench_with({"left_motor": [0.9] * 20, "right_motor": [-0.9] * 20})
    anomalies = bench._analyze_energy()
    assert len(anomalies) == 1
    assert anomalies[0].pattern_type == "over_energy"


def test_moderate_energy_is_clean():
    bench = bench_with({"left_motor": [0.3] * 20, "right_motor": [0.3] * 20})
    assert bench._analyze_energy() == []
