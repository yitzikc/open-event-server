"""empty message

Revision ID: 3ddac4799fb1
Revises: 15f1533bb93d
Create Date: 2016-06-17 11:29:40.419114

"""

# revision identifiers, used by Alembic.
revision = '3ddac4799fb1'
down_revision = '15f1533bb93d'

from alembic import op
import sqlalchemy as sa
import sqlalchemy_utils


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.add_column('user', sa.Column('is_super_admin', sa.Boolean(), nullable=True))
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('user', 'is_super_admin')
    ### end Alembic commands ###