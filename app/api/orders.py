from datetime import datetime
from flask import request, render_template
from flask_jwt import current_identity as current_user
from flask_rest_jsonapi import ResourceDetail, ResourceList, ResourceRelationship
from marshmallow_jsonapi import fields
from marshmallow_jsonapi.flask import Schema

from app.api.bootstrap import api
from app.api.data_layers.ChargesLayer import ChargesLayer
from app.api.helpers.db import save_to_db, safe_query
from app.api.helpers.exceptions import ForbiddenException, UnprocessableEntity
from app.api.helpers.files import create_save_pdf
from app.api.helpers.mail import send_email_to_attendees
from app.api.helpers.permission_manager import has_access
from app.api.helpers.permissions import jwt_required
from app.api.helpers.ticketing import TicketingManager
from app.api.helpers.utilities import dasherize, require_relationship
from app.api.schema.orders import OrderSchema
from app.models import db
from app.models.discount_code import DiscountCode, TICKET
from app.models.order import Order, OrderTicket


class OrdersListPost(ResourceList):
    def before_post(self, args, kwargs, data=None):
        require_relationship(['event', 'ticket_holders'], data)
        if not has_access('is_coorganizer', event_id=data['event']):
            data['status'] = 'pending'

    def before_create_object(self, data, view_kwargs):
        # Apply discount only if the user is not event admin
        if data.get('discount') and not has_access('is_coorganizer', event_id=data['event']):
            discount_code = safe_query(self, DiscountCode, 'id', data['discount'], 'discount_code_id')
            if not discount_code.is_active:
                raise UnprocessableEntity({'source': 'discount_code_id'}, "Inactive Discount Code")
            else:
                now = datetime.utcnow()
                valid_from = datetime.strptime(discount_code.valid_from, '%Y-%m-%d %H:%M:%S')
                valid_till = datetime.strptime(discount_code.valid_till, '%Y-%m-%d %H:%M:%S')
                if not (valid_from <= now <= valid_till):
                    raise UnprocessableEntity({'source': 'discount_code_id'}, "Inactive Discount Code")
                if not TicketingManager.match_discount_quantity(discount_code, data['ticket_holders']):
                    raise UnprocessableEntity({'source': 'discount_code_id'}, 'Discount Usage Exceeded')

            if discount_code.event.id != data['event'] and discount_code.user_for == TICKET:
                raise UnprocessableEntity({'source': 'discount_code_id'}, "Invalid Discount Code")

    def after_create_object(self, order, data, view_kwargs):
        order_tickets = {}
        for holder in order.ticket_holders:
            pdf = create_save_pdf(render_template('/pdf/ticket_attendee.html', order=order, holder=holder))
            holder.pdf_url = pdf
            save_to_db(holder)
            if order_tickets.get(holder.ticket_id) is None:
                order_tickets[holder.ticket_id] = 1
            else:
                order_tickets[holder.ticket_id] += 1
        for ticket in order_tickets:
            od = OrderTicket(order_id=order.id, ticket_id=ticket, quantity=order_tickets[ticket])
            save_to_db(od)
        order.quantity = order.get_tickets_count()
        save_to_db(order)
        if not has_access('is_coorganizer', **view_kwargs):
            TicketingManager.calculate_update_amount(order)
        send_email_to_attendees(order)

        data['user_id'] = current_user.id

    methods = ['POST', ]
    decorators = (jwt_required,)
    schema = OrderSchema
    data_layer = {'session': db.session,
                  'model': Order,
                  'methods': {'before_create_object': before_create_object,
                              'after_create_object': after_create_object
                              }}


class OrdersList(ResourceList):
    def before_get(self, args, kwargs):
        if kwargs.get('event_id') is None:
            if 'GET' in request.method and has_access('is_admin'):
                pass
            else:
                raise ForbiddenException({'source': ''}, "Admin Access Required")
        elif not has_access('is_coorganizer', event_id=kwargs['event_id']):
            raise ForbiddenException({'source': ''}, "Co-Organizer Access Required")

    decorators = (jwt_required,)
    schema = OrderSchema
    data_layer = {'session': db.session,
                  'model': Order}


class OrderDetail(ResourceDetail):
    def before_update_object(self, order, data, view_kwargs):
        if data.get('status'):
            if has_access('is_coorganizer', event_id=order.event.id):
                pass
            else:
                raise ForbiddenException({'pointer': 'data/status'},
                                         "To update status minimum Co-organizer access required")

    decorators = (api.has_permission('is_coorganizer', fetch="event_id", fetch_as="event_id",
                                     fetch_key_model="identifier", fetch_key_url="order_identifier", model=Order),)

    schema = OrderSchema
    data_layer = {'session': db.session,
                  'model': Order,
                  'url_field': 'order_identifier',
                  'id_field': 'identifier',
                  'methods': {
                      'before_update_object': before_update_object
                  }}


class OrderRelationship(ResourceRelationship):
    decorators = (jwt_required,)
    schema = OrderSchema
    data_layer = {'session': db.session,
                  'model': Order}


class ChargeSchema(Schema):
    class Meta:
        type_ = 'charge'
        inflect = dasherize
        self_view = 'v1.charge_list'
        self_view_kwargs = {'id': '<id>'}

    id = fields.Str(dump_only=True)
    stripe = fields.Str(allow_none=True)


class ChargeList(ResourceList):
    methods = ['POST', ]
    schema = ChargeSchema

    data_layer = {
        'class': ChargesLayer,
        'session': db.session
    }