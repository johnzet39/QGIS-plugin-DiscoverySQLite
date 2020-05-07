# -*- coding: utf-8 -*-

# Discovery Plugin
#
# Copyright (C) 2015 Lutra Consulting
# info@lutraconsulting.co.uk
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from PyQt4.QtCore import *

import sqlite3


def _quote(identifier):
    """ quote identifier """
    return u'"%s"' % identifier.replace('"', '""')

def _quote_str(txt):
    """ make the string safe - replace ' with '' """
    return txt.replace("'", "''")


def get_search_sql(search_text, search_column, table):
    """ Returns a tuple: (SQL query text, dictionary with values to replace variables with).
    """

    """
    Spaces in queries
        A query with spaces is executed as follows:
            'my query'
            ILIKE '%my%query%'

    A note on spaces in postcodes
        Postcodes must be stored in the DB without spaces:
            'DL10 4DQ' becomes 'DL104DQ'
        This allows users to query with or without spaces
        As wildcards are inserted at spaces, it doesn't matter whether the query is:
            'dl10 4dq'; or
            'dl104dq'
    """

    wildcarded_search_string = ''
    for part in search_text.split():
        wildcarded_search_string += '%' + part
    wildcarded_search_string += '%'
    wildcarded_search_string = wildcarded_search_string
    query_dict = {'search_text': wildcarded_search_string}

    print type(wildcarded_search_string)

    query_text = "SELECT WKT_GEOMETRY AS geom, {0} AS suggestion_string FROM {1} WHERE {0} LIKE '{2}' ORDER BY {0} LIMIT 1000".format(search_column, table, wildcarded_search_string.encode('ascii'))


    return query_text, query_dict