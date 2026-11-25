# Team review: repo configuration

<!--
Copy this file to `.claude/team-review.md` in a repository to configure the team review for that repo.
Every section is optional. The context builder reads it as plain text, so free-form notes are fine.
-->

## Stack

- Kotlin 2.0, Spring Boot 3.3, PostgreSQL 15, Kafka, Gradle, Helm

## ADR directory

docs/adrs

## Ignore paths

Changes under these paths are not reviewed (generated code, snapshots, vendored files):

- src/generated/**
- **/__snapshots__/**

## Project rules

- All monetary amounts use `Money` (minor units, Long); never Double or BigDecimal directly.
- Controllers only map DTOs; business logic lives in `*Service` classes.
- Every Kafka consumer is idempotent on `eventId`.
