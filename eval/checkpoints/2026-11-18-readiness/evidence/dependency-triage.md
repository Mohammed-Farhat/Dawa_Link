# Dependency findings triage

Original npm audit: eight high-severity affected package nodes, all in the build/test
chain (vite, vitest, @vitejs/plugin-react, picomatch/fdir/tinyglobby,
postcss-mixins/preset-mantine). These are not eight independent demonstrated exploits.
The original audit JSON preserves advisory URLs/ranges and npm's suggested major
version downgrades. Runtime production risk has not been established from these counts.
Local test servers bind loopback; untrusted project/build inputs are not accepted.
Do not blindly apply npm audit fix --force: its major downgrades would change the
reference toolchain and invalidate comparison provenance. Review dependency upgrades
in separate infrastructure work, with frontend tests/build and fresh audit evidence.
