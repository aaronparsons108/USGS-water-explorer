"""Vendored compute for the nitro-research explorer.

Faithful ports of the per-site metric logic from the research1 ``nitro`` and
``dissolved_oxygen`` packages, reorganized so this repo stands alone. Every
metric (median streamflow, median NO3+NO2, median dissolved oxygen, and the two
mutual-information measures) is an aggregate of a small set of per-day, per-site
tables; we parse the raw sitedata once (``loader`` + ``cache``) and recompute
medians / MI over any date or season slice in memory (``metrics``).
"""
