def wilson(k, n, z=1.96):
    """
    Compute the Wilson score interval for a binomial proportion.

    Parameters
    ----------
    k : int
        Number of successes.
    n : int
        Number of trials.
    z : float, optional
        Z-score for the desired confidence level (default is 1.96 for 95% confidence).

    Returns
    -------
    tuple
        Lower and upper bounds of the Wilson score interval.
    """
    if n == 0:
        return 0.0, 0.0
    p, d = k / n, 1 + z * z /n
    c = (p + z * z / (2 * n)) / d
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, c - m), min(1.0, c + m)
