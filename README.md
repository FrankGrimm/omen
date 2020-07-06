[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![OSS Lifecycle](https://img.shields.io/osslifecycle/Netflix/osstracker.svg)]()
[![Docker](https://github.com/FrankGrimm/omen/workflows/Docker/badge.svg)](https://github.com/FrankGrimm/omen/packages)

# OMEN - A dockerized, collaborative, document annotation platform

![screen rec](https://frankgrimm.github.io/omen/img/screen_rec.gif)

## Setup

**Note**: This information is outdated, a full setup guide is coming soon.

- Install PostgreSQL v9.4+
- Create postgres database from `schema.sql` and edit `config.json` for credentials.
- Create admin user: `./bin/create_user`
- Start server: `./bin/run`
Reading package lists...
Building dependency tree...
Reading state information...
libpq-dev is already the newest version (12.2-2.pgdg16.04+1).
0 upgraded, 0 newly installed, 0 to remove and 273 not upgraded.
