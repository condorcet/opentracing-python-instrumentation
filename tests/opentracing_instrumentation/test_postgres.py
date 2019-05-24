# coding: utf-8
# Copyright (c) 2018 Uber Technologies, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
from builtins import object
import psycopg2 as psycopg2_client
from psycopg2 import sql

from basictracer import BasicTracer
from basictracer.recorder import InMemoryRecorder
import opentracing

from opentracing_instrumentation.client_hooks import psycopg2


from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
)
from sqlalchemy.orm import mapper, sessionmaker

import pytest


POSTGRES_CONNECTION_STRING = 'postgresql://cloud:cloud@localhost/travis_ci_test'


@pytest.fixture
def engine():
    try:
        yield create_engine(POSTGRES_CONNECTION_STRING)
    except:
        pass


@pytest.fixture
def session():
    Session = sessionmaker()
    Session.configure(bind=engine)
    try:
        yield Session()
    except:
        pass


@pytest.fixture(autouse=True)
def patch_postgres():
    psycopg2.install_patches()


@pytest.fixture()
def tracer():
    t = BasicTracer(recorder=InMemoryRecorder())
    old_tracer = opentracing.tracer
    opentracing.tracer = t

    try:
        yield t
    except:
        opentracing.tracer = old_tracer


metadata = MetaData()
user = Table('user', metadata,
             Column('id', Integer, primary_key=True),
             Column('name', String(50)),
             Column('fullname', String(50)),
             Column('password', String(12)))


class User(object):

    def __init__(self, name, fullname, password):
        self.name = name
        self.fullname = fullname
        self.password = password


mapper(User, user)


@pytest.fixture()
def connection():
    return psycopg2_client.connect(POSTGRES_CONNECTION_STRING)


def is_postgres_running():
    try:
        with psycopg2_client.connect(POSTGRES_CONNECTION_STRING) as conn:
            pass
        return True
    except:
        return False


@pytest.mark.skipif(not is_postgres_running(), reason='Postgres is not running or cannot connect')
def test_db(tracer, engine, session):
    metadata.create_all(engine)
    user1 = User(name='user1', fullname='User 1', password='password')
    user2 = User(name='user2', fullname='User 2', password='password')
    session.add(user1)
    session.add(user2)
    # If the test does not raised an error, it is passing

@pytest.mark.skipif(not is_postgres_running(), reason='Postgres is not running or cannot connect')
def test_connection_proxy(tracer, engine):
    # Test that connection properties are proxied by ContextManagerConnectionWrapper
    assert engine.raw_connection().connection.closed == 0


@pytest.mark.skipif(not is_postgres_running(), reason='Postgres is not running or cannot connect')
@pytest.mark.parametrize('query', [
    # plain string
    '''SELECT %s;''',
    # uincode
    u'''SELECT %s; -- хеллоу''',
    # Composed
    sql.Composed([sql.SQL('''SELECT %s;''')]),
    # Identifier
    sql.SQL('''SELECT %s FROM {} LIMIT 1;''').format(
        sql.Identifier('pg_catalog', 'pg_database')
    ),
    # Literal
    sql.SQL('''SELECT {}''').format(sql.Literal('foobar')),
    # Placeholder
    sql.SQL('''SELECT {}''').format(sql.Placeholder())
], ids=('str', 'unicode', 'Composed', 'Identifier', 'Literal', 'Placeholder'))
def test_execute_sql(tracer, engine, session, connection, query):

    # Check that executing with objects of ``sql.Composable`` subtypes doesn't
    # raise any exceptions.

    metadata.create_all(engine)
    user1 = User(name='user1', fullname='User 1', password='password')
    session.add(user1)
    with tracer.start_span('test'):
        cur = connection.cursor()
        cur.execute(query, ('foobar', ))
        assert cur.fetchall() == [('foobar', )]
