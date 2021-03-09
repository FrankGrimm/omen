"""
This module stores the declarative base instance for SQLAlchemy
in order not to introduce cyclic imports between the main
database module and model implementations.
"""
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
