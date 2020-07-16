# Configuration

The configuration is, by default, stored in a JSON formatted file called `./config.json`.

Users can override the location of the configuration file by setting the environment variable `OMEN_CONFIG_FILENAME`.

Users can override any configuration value by passing the respective equivalent as environment variables. Option keys can be translated to environment variables by:
- Prefixing the key with `OMEN_`, e.g. `option key` => `OMEN_option key`.
- Replacing all spaces with underscores, e.g. `OMEN_option key` => `OMEN_option_key`.
- Converting the whole key to uppercase letters, e.g. `OMEN_option_key` => `OMEN_OPTION_KEY`.

 **Logging in the production container** 

The gunicorn/production container supports all general options [documented here](https://github.com/tiangolo/meinheld-gunicorn-flask-docker). It additionally allows users to map in a log directory into `/home/omenuser/` (configurable via environment variable `LOGDIR`, which defaults to `~/logs`).

### Settings

| key                    | value                                                    | description                                                                                                                                                                                      |
|------------------------|----------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| dbconnection           | postgresql+psycopg2://username:password@host:port/schema | The [SQLAlchemy](https://docs.sqlalchemy.org/en/13/core/connections.html) connection string to your database instance.                                                                           |
| flask_secret           | random string                                            | The [flask secret key](https://flask.palletsprojects.com/en/1.1.x/tutorial/deploy/?highlight=secret#configure-the-secret-key) used for flask-related ciphers (e.g. protecting session IDs).      |
| log_level              | debug / info                                             | Which [Python `logging`](https://docs.python.org/3/howto/logging.html) log level to use. Test instances are recommended to use `debug`, while production environments will likely prefer `info`. |
| tag_orientation_cutoff | int, default: 5                                          | At which number of tags / labels to switch from horizontal display to the vertical layout. Note: This setting is likely to be removed in a future version.                                       |
