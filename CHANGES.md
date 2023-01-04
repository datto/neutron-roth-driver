# Change Log

All notable changes will be documented in this file.

## [0.0.3] - 2022-06-20

### Added

- Neutron router frr support
  The agent now supports adding frr namespace instances to neutron routers
  to dynamically advertise connected routes via the provider interface.
  Only prefixes in the same shared address scope as the provider prefix are considered.
  Prefixes must be members of subnet pools.

### Changed

### Fixed
