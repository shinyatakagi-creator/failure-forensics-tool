# data_sync

Sync jobs take a lock with a 900 second lease. If a run is still active when the lease ends, another run may start.
