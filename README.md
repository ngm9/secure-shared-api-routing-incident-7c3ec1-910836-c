## Task Overview
Utkrusht runs two small marketplace APIs that support candidate profiles and assessment sessions for internal product teams. Both are supposed to be available through one secure customer-facing entry point so dependent teams can call them consistently. This path has been running for a while and the ordinary path is expected to work. The release engineering, developer, and SRE teams have reported behaviour that does not fit a cluster they rely on, and those reports are listed under Objectives. Your job is to look into each one and make the cluster serve traffic the way it is supposed to.

## Objectives
- The release engineer was validating the public entry point and noticed the secure version of the shared domain did not present the expected application identity. This should not happen.
- A developer testing the second API found that its replicas never became available even after waiting for normal startup. This should not happen.
- The SRE noticed that after earlier startup errors were cleared, the second API still did not fully come online and the scheduler reported it had nowhere suitable to place more work.

## Helpful Tips
- Look at the cluster as it is right now before you change anything — what's running, what isn't, and why.
- Reproduce what each team saw before deciding what to change; describe and event output can help explain what actually happened.
- When something looks fixed, check the whole picture again rather than trusting the first sign of success.
- Whatever you change should still be checkable by hand afterwards; a visual dashboard is also available if you prefer to look around that way.

## How to Verify
- The shared secure entry point should return healthy responses for both APIs.
- The second API should become available with all expected replicas healthy.
- The two APIs should remain placed and stable together on the single machine.
- The grader suite under tests/ exercises these behaviours directly against the live cluster.
