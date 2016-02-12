# -*- coding: utf-8 -*-

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base

from postgresql_audit import VersioningManager

from .utils import last_activity


@pytest.fixture()
def schema_name():
    return 'audit'


@pytest.fixture()
def versioning_manager(schema_name):
    return VersioningManager(schema_name=schema_name)


@pytest.yield_fixture()
def Activity(base, versioning_manager):
    versioning_manager.init(base)
    yield versioning_manager.activity_cls
    versioning_manager.remove_listeners()


@pytest.yield_fixture()
def table_creator(
        base,
        connection,
        session,
        models,
        versioning_manager,
        schema_name
):
    sa.orm.configure_mappers()
    connection.execute('DROP SCHEMA IF EXISTS {} CASCADE'.format(schema_name))
    tx = connection.begin()
    versioning_manager.activity_cls.__table__.create(connection)
    base.metadata.create_all(connection)
    tx.commit()
    yield
    base.metadata.drop_all(connection)
    session.commit()


@pytest.mark.usefixtures('Activity', 'table_creator')
class TestCustomSchemaActivityCreation(object):
    def test_insert(self, user, connection, schema_name):
        activity = last_activity(connection, schema=schema_name)
        assert activity['old_data'] is None
        assert activity['changed_data'] == {
            'id': user.id,
            'name': 'John',
            'age': 15
        }
        assert activity['table_name'] == 'user'
        assert activity['transaction_id'] > 0
        assert activity['verb'] == 'insert'

    def test_operation_after_commit(
        self,
        Activity,
        User,
        session
    ):
        user = User(name='Jack')
        session.add(user)
        session.commit()
        user = User(name='Jack')
        session.add(user)
        session.commit()
        assert session.query(Activity).count() == 2

    def test_operation_after_rollback(
        self,
        Activity,
        User,
        session
    ):
        user = User(name='John')
        session.add(user)
        session.rollback()
        user = User(name='John')
        session.add(user)
        session.commit()
        assert session.query(Activity).count() == 1

    def test_manager_defaults(
        self,
        User,
        session,
        versioning_manager,
        schema_name
    ):
        versioning_manager.values = {'actor_id': 1}
        user = User(name='John')
        session.add(user)
        session.commit()
        activity = last_activity(session, schema=schema_name)
        assert activity['actor_id'] == '1'

    def test_callables_as_manager_defaults(
        self,
        User,
        session,
        versioning_manager,
        schema_name
    ):
        versioning_manager.values = {'actor_id': lambda: 1}
        user = User(name='John')
        session.add(user)
        session.commit()
        activity = last_activity(session, schema=schema_name)
        assert activity['actor_id'] == '1'

    def test_raw_inserts(
        self,
        User,
        session,
        versioning_manager,
        schema_name
    ):
        versioning_manager.values = {'actor_id': 1}
        session.execute(User.__table__.insert().values(name='John'))
        session.execute(User.__table__.insert().values(name='John'))
        versioning_manager.set_activity_values(session)
        activity = last_activity(session, schema=schema_name)

        assert activity['actor_id'] == '1'

    def test_activity_repr(self, Activity):
        assert repr(Activity(id=3, table_name='user')) == (
            "<Activity table_name='user' id=3>"
        )

    def test_custom_actor_class(self, User, schema_name):
        manager = VersioningManager(
            actor_cls=User,
            schema_name=schema_name
        )
        manager.init(declarative_base())
        sa.orm.configure_mappers()
        assert isinstance(
            manager.activity_cls.actor_id.property.columns[0].type,
            sa.Integer
        )
        assert manager.activity_cls.actor
        manager.remove_listeners()

    def test_data_expression_sql(self, Activity):
        assert str(Activity.data) == (
            'jsonb_merge(audit.activity.old_data, audit.activity.changed_data)'
        )

    def test_data_expression(self, user, session, Activity):
        user.name = 'Luke'
        session.commit()
        assert session.query(Activity).filter(
            Activity.table_name == 'user',
            Activity.data['id'].cast(sa.Integer) == user.id
        ).count() == 2

    def test_custom_string_actor_class(self, schema_name):
        base = declarative_base()

        class User(base):
            __tablename__ = 'user'
            id = sa.Column(sa.Integer, primary_key=True)

        User()
        manager = VersioningManager(
            actor_cls='User',
            schema_name=schema_name
        )
        manager.init(base)
        sa.orm.configure_mappers()
        assert isinstance(
            manager.activity_cls.actor_id.property.columns[0].type,
            sa.Integer
        )
        assert manager.activity_cls.actor
        manager.remove_listeners()