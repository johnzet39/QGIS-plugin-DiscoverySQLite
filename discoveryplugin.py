# -*- coding: utf-8 -*-

# Discovery SQLite Plugin (Zlatanov Evgeniy)
# Discovery Plugin Modification

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import QComboBox, QLabel, QCompleter, QTableView, QHeaderView
from PyQt5 import uic

import time
import types
import os.path

from qgis.core import *
from qgis.gui import *
from qgis.utils import iface

# import dbutils
import codecs
import re, sqlite3
from .resources import *

class DiscoveryPlugin:

    def __init__(self, _iface):
        # Save reference to the QGIS interface
        self.iface = _iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)

        # Variables to facilitate delayed queries and database connection management
        self.icon_loading = ':plugins/_Discovery_sqlite/icons/loading.gif'
        self.db_timer = QTimer()
        self.line_edit_timer = QTimer()
        self.line_edit_timer.setSingleShot(True)
        self.line_edit_timer.timeout.connect(self.reset_line_edit_after_move)
        self.next_query_time = None
        self.last_query_time = time.time()
        self.db_conn = None
        self.search_delay = 0.5  # s
        self.query_sql = ''
        self.query_text = ''
        self.query_dict = {}
        self.db_idle_time = 60.0  # s

        self.search_results = []
        self.tool_bar = None
        self.search_line_edit = None
        self.completer = None

        self.marker = QgsVertexMarker(iface.mapCanvas())
        self.marker.setIconSize(15)
        self.marker.setPenWidth(2)
        self.marker.setColor(QColor(226,27,28)) #51,160,44))
        self.marker.setZValue(11)
        self.marker.setVisible(False)
        self.marker2 = QgsVertexMarker(iface.mapCanvas())
        self.marker2.setIconSize(16)
        self.marker2.setPenWidth(4)
        self.marker2.setColor(QColor(255,255,255,200))
        self.marker2.setZValue(10)
        self.marker2.setVisible(False)

    def initGui(self):

        # Create a new toolbar
        self.tool_bar = self.iface.addToolBar(u'Панель поиска')
        self.tool_bar.setObjectName('Discovery_sqlite_Plugin')

                # Add search edit box
        self.search_line_edit = QgsFilterLineEdit()
        self.search_line_edit.setSelectOnFocus(True)
        self.search_line_edit.setShowSearchIcon(True)
        self.search_line_edit.setPlaceholderText(u'Поиск адреса или участка...')
        # self.search_line_edit.setMaximumWidth(768)
        self.tool_bar.addWidget(self.search_line_edit)

        # loading indicator
        self.load_movie = QMovie()
        self.label_load = QLabel()
        self.tool_bar.addWidget(self.label_load)

        # Set up the completer
        model = QStandardItemModel()
        self.completer = QCompleter([])  # Initialise with en empty list
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setMaxVisibleItems(30)
        self.completer.setModelSorting(QCompleter.UnsortedModel)  # Sorting done in PostGIS
        self.completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)  # Show all fetched possibilities
        self.completer.setModel(model)
        tableView = QTableView()
        tableView.verticalHeader().setVisible(False)
        tableView.horizontalHeader().setVisible(False)
        tableView.setSelectionBehavior(QTableView.SelectRows)
        tableView.setShowGrid(False)
        # tableView.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        tableView.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        fontsize = QFontMetrics(tableView.verticalHeader().font()).height() + 2#font size
        tableView.verticalHeader().setDefaultSectionSize(fontsize) #font size 15
        tableView.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        tableView.horizontalHeader().setStretchLastSection(True)
        tableView.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.completer.setCompletionColumn(0)
        self.completer.setPopup(tableView)

        self.completer.activated[QModelIndex].connect(self.on_result_selected)
        self.completer.highlighted[QModelIndex].connect(self.on_result_highlighted)
        self.search_line_edit.setCompleter(self.completer)

        # Connect any signals
        self.search_line_edit.textEdited.connect(self.on_search_text_changed)
        self.search_line_edit.returnPressed.connect(self.returnPressed)

        self.read_config()

        # Search results
        self.search_results = []

        # Set up a timer to periodically perform db queries as required
        self.db_timer.timeout.connect(self.schedule_search)


    def read_config(self):
        qstring = ''
        self.data = self.settings_path()
        try:
            for line in self.data[1:]:
                words = line.split(';')
                postgissearchcolumn = words[2].strip()
                postgistable = words[0].strip()
                geomcolumn = words[3].strip()
                layername = words[4].strip()
                isSelect = int(words[5].strip())

                connection = sqlite3.connect(os.path.join(self.dbfile.strip()))

                cur = connection.cursor()

                qstring = u'select {2} from {0} where length({1})>0 LIMIT 1'.format(postgistable, postgissearchcolumn, geomcolumn)
                cur.execute(qstring)
                connection.close()
            self.make_enabled(True)   # assume the config is invalid first   
        except Exception as E:
            print(E)
            self.make_enabled(False)

    # включить или выключить поисковую строку в зависимости от результата проверки настроек
    def make_enabled(self, enabled):
        self.search_line_edit.setEnabled(enabled)
        self.search_line_edit.setPlaceholderText(u"Поиск адреса или участка..." if enabled else u"Поиск отключен: проверьте конфигурацию")


    def settings_path(self):
        p = os.path.join(self.plugin_dir, 'layers.ini')
        f=codecs.open(p, 'r', encoding='cp1251')
        data = f.readlines()

        dbfileline = data[0]
        if dbfileline[:2] == u'\\\\':
            self.dbfile = dbfileline
        elif dbfileline[1]==u':':
            self.dbfile = dbfileline
        else:
            self.dbfile = os.path.join(self.plugin_dir, dbfileline)
        f.close()
        return data

    def unload(self):
        self.db_timer.stop()
        self.db_timer.timeout.disconnect(self.schedule_search)
        self.completer.highlighted[QModelIndex].disconnect(self.on_result_highlighted)
        self.completer.activated[QModelIndex].disconnect(self.on_result_selected)
        self.search_line_edit.textEdited.disconnect(self.on_search_text_changed)
        self.search_line_edit.returnPressed.disconnect(self.returnPressed)
        self.tool_bar.clear()  # Clear all actions
        self.iface.mainWindow().removeToolBar(self.tool_bar)


    def clear_suggestions(self):
        model = self.completer.model()
        model.clear()
        # model.setStringList([])

    def returnPressed(self):
        if self.completer.popup().isHidden():
            self.do_search(self.search_line_edit.text())

    # def setLoading(self, isLoading):
    #     if self.label_load is None:
    #         return
    #     if isLoading:
    #         load_movie = QMovie()
    #         load_movie.setFileName(self.icon_loading)
    #         self.label_load.setMovie(load_movie)
    #         load_movie.start()
    #     else:
    #         load_movie = QMovie()
    #         load_movie.stop()
    #         self.label_load.setMovie(load_movie)

    def schedule_search(self):

        if self.next_query_time is not None and self.next_query_time < time.time():
            self.next_query_time = None  # Prevent this query from being repeated
            self.last_query_time = time.time()
            self.do_search(self.search_line_edit.text())
            self.db_timer.stop()
            # self.setLoading(False)
            self.search_line_edit.setShowSpinner(False)
        else:
            # self.setLoading(True)
            self.search_line_edit.setShowSpinner(True)
            if time.time() > self.last_query_time + self.db_idle_time:
                self.db_conn = None

    # def on_search_text_changed(self, new_search_text):
    def on_search_text_changed(self, new_search_text):
        # self.setLoading(False)
        self.search_line_edit.setShowSpinner(False)
        if len(new_search_text) < 3:
            self.db_timer.stop()
            self.clear_suggestions()
            return
        self.db_timer.start(300)
        self.next_query_time = time.time() + self.search_delay


    def do_search(self, new_search_text):

        if len(new_search_text) < 3:
            self.clear_suggestions()
            return

        self.clear_suggestions()

        self.query_text = new_search_text

        self.search_results = []
        self.suggestions = []

        for index, line in enumerate(self.data[1:]):
            curline_layer= line
            words = curline_layer.split(';')
            searchcolumn = words[2].strip() # поле со значением для поиска
            postgistable = words[0].strip() # таблица
            geomcolumn = words[3].strip() # поле с геометрией
            layername = words[4].strip() # имя слоя в легенде для соответствий и выделения
            isSelect = int(words[5].strip()) # выделять ли объект в слое layername
            descript = words[1].strip() # описание. Выводится в списке результатов

            query_text, query_dict = self.get_search_sql(new_search_text, searchcolumn, postgistable)
            
            query_sql = query_text
            query_dict = query_dict
            self.perform_search(query_sql, query_dict, descript, postgistable, layername, isSelect, searchcolumn)

        # QStringList - просто одна строка в выводе
        # if len(self.suggestions) > 0:   
        #     model = self.completer.model()
        #     model.setStringList(self.suggestions)
        #     print(model)
        #     self.completer.complete()

        if len(self.suggestions) > 0:
            # model = self.completer.model()
            model = QStandardItemModel()
            font = QFont()
            font.setItalic(True)
            font.setPointSize(7)
            # заполняем модель
            for i, line in enumerate(self.suggestions):
                #icon
                pixmap = QPixmap(':plugins/_Discovery_sqlite/icons/'+line[2]+'.png')
                pixmap = pixmap.scaledToHeight(10)
                pixmap = pixmap.scaledToWidth(10)
                # itemImage = QStandardItem()
                # itemImage.setData(pixmap, Qt.DecorationRole)
                # model.setItem(i, 0, itemImage)

                itemLayer = QStandardItem(u"{1}[{0}]".format(line[1], u' '*50))
                itemLayer.setFont(font)
                itemValue = QStandardItem(line[0])
                itemValue.setData(pixmap, Qt.DecorationRole)
                model.setItem(i, 0, itemValue)
                model.setItem(i, 1, itemLayer)

            self.completer.setModel(model)
            self.completer.complete()

        else:
            model = self.completer.model()
            # self.suggestions.append(u"<Не найдено>")   # для QStringList
            # model.setStringList(self.suggestions)   # для QStringList
            model.setItem(0,0,QStandardItem('<Не найдено>')) # для QStandardItemModel
            self.completer.complete()


    def perform_search(self, query_sql, query_dict, descript, tablename, layername, isSelect, searchcolumn):
        cur = self.get_db_cur()
        cur.execute(query_sql, query_dict)
        for row in cur.fetchall():
            geom, suggestion_text = row[0], row[1]
            self.search_results.append(geom)
            self.suggestions.append([suggestion_text, descript, tablename, layername, isSelect, searchcolumn])
            # self.suggestions.append(suggestion_text)   # для QStringList


    def get_search_sql(self, search_text, search_column, table):

        wildcarded_search_string = ''
        for part in search_text.split():
            wildcarded_search_string += '%' + part#.lower()
        wildcarded_search_string += '%'
        wildcarded_search_string = wildcarded_search_string
        query_dict = {'search_text': wildcarded_search_string}

        # wildcarded_search_string = wildcarded_search_string.encode('cp1251')
        query_text = u"SELECT WKT_GEOMETRY AS geom, {0} AS suggestion_string FROM {1} WHERE ({0}) LIKE '{2}' ORDER BY {0} LIMIT 1000".format(search_column, table, wildcarded_search_string)
        # query_text = query_text.decode('cp1251')
        return query_text, query_dict

    def on_result_selected(self, result_index):
        resultIndexRow = result_index.row()

        if len(self.search_results) < 1:
            self.search_line_edit.setPlaceholderText(u'')
            return
        # What to do when the user makes a selection
        geometry_text = self.search_results[resultIndexRow]
        location_geom = QgsGeometry.fromWkt(geometry_text)
        canvas = self.iface.mapCanvas()
        # dst_srid = canvas.mapRenderer().destinationCrs().authid()
        # Ensure the geometry from the DB is reprojected to the same SRID as the map canvas
        location_centroid = location_geom.centroid().asPoint()

        result_text = self.completer.completionModel().index(resultIndexRow, 0).data()

        if self.suggestions[resultIndexRow][2] in (u"adres_nd") and location_geom.type() == 0: # point
            self.show_marker(location_centroid)
            self.iface.mapCanvas().setExtent(location_geom.boundingBox())
            self.iface.mapCanvas().zoomScale(1000)
            layer_build = self.find_layer(u"Здания")
            if layer_build != None:
                layer_build.selectByIds([])
                for feat in layer_build.getFeatures(QgsFeatureRequest().setFilterRect(QgsRectangle(self.iface.mapCanvas().extent()))):
                    if location_geom.intersects(feat.geometry()):
                        # self.show_marker_feature(feat.geometry())
                        self.iface.setActiveLayer(layer_build)
                        layer_build.selectByIds([feat.id()])
                        layer_build.triggerRepaint()
                        return
        
        else:   #not point
            layername = self.suggestions[resultIndexRow][3]
            isSelect = self.suggestions[resultIndexRow][4]
            searchcolumn = self.suggestions[resultIndexRow][5]

            box = location_geom.boundingBox()
            if box.height()>box.width():
                max=box.height()
            else:
                max=box.width()
            box.grow(max*0.10)
            self.iface.mapCanvas().setExtent(box)

            if isSelect == 1:
                selLayer = self.find_layer(layername)
                if selLayer is not None:
                    for feat in selLayer.getFeatures(QgsFeatureRequest().setFilterRect(box)):
                        # print(feat[searchcolumn], str(result_text).strip())
                        try:
                            if str(feat[searchcolumn]) == str(result_text).strip():
                                self.iface.setActiveLayer(selLayer)
                                selLayer.selectByIds([feat.id()])
                                selLayer.triggerRepaint()
                                break
                        except Exception as E:
                            print(E)
                            break

            self.show_marker_feature(location_geom)

        canvas.refresh()
        self.line_edit_timer.start(0)
        # self.db_timer.stop()

    def get_db_cur(self):
        # Create a new new connection if required
        if self.db_conn is None:
            self.db_conn = sqlite3.connect(os.path.join(self.dbfile.strip()))
        return self.db_conn.cursor()


    def on_result_highlighted(self, result_idx):
        self.line_edit_timer.start(0)

    def reset_line_edit_after_move(self):
        self.search_line_edit.setText(self.query_text)

    def find_layer(self, layer_name):
        for search_layer in self.iface.mapCanvas().layers():
            if search_layer.name() == layer_name:
                return search_layer
        return None

    def show_marker(self, point):
        for m in [self.marker, self.marker2]:
            m.setCenter(point)
            m.setOpacity(1.0)
            m.setVisible(True)
        QTimer.singleShot(4000, self.hide_marker)

    def hide_marker(self):
        opacity = self.marker.opacity()
        if opacity > 0.:
            # produce a fade out effect
            opacity -= 0.1
            self.marker.setOpacity(opacity)
            self.marker2.setOpacity(opacity)
            QTimer.singleShot(100, self.hide_marker)
        else:
            self.marker.setVisible(False)
            self.marker2.setVisible(False)

    def show_marker_feature(self, geom):
        if geom.type() == 2: #poly
            self.r = QgsRubberBand(iface.mapCanvas(), True)
        elif geom.type() == 1: #line
            self.r  = QgsRubberBand(iface.mapCanvas(), False)
        self.r.setToGeometry(geom, None)
        self.r.setColor(QColor(255,0,0,200))
        self.r.setFillColor(QColor(255,0,0,50))
        self.r.setWidth(2)
        self.r.setZValue(9)

        QTimer.singleShot(4000, self.hide_marker_feature)


    def hide_marker_feature(self):
        opacity = self.r.opacity()
        if opacity > 0.:
            # produce a fade out effect
            opacity -= 0.1
            self.r.setOpacity(opacity)
            QTimer.singleShot(100, self.hide_marker_feature)
        else:
            iface.mapCanvas().scene().removeItem(self.r)




    # # Переопределение оператора сравнения с двумя и тремя параметрами
    # def sqlite_like(self, template_, value_):
    #     return  sqlite_like_escape(template_, value_, None)
    
    # def sqlite_like_escape(self, template_, value_, escape_):
    #     re_ = re.compile(template_.lower().
    #                         replace(".", "\\.").replace("^", "\\^").replace("$", "\\$").
    #                         replace("*", "\\*").replace("+", "\\+").replace("?", "\\?").
    #                         replace("{", "\\{").replace("}", "\\}").replace("(", "\\(").
    #                         replace(")", "\\)").replace("[", "\\[").replace("]", "\\]").
    #                         replace("_", ".").replace("%", ".*?"))
    #     return re_.match(value_.lower()) != None    
        
    # # Переопределение функции преобразования к нижнему регистру
    # def sqlite_lower(self, value_):
    #     return value_.lower()
          
    # # Переопределение правила сравнения строк
    # def sqlite_nocase_collation(self, value1_, value2_):
    #     return cmp(value1_.decode('utf-8').lower(), value2_.decode('utf-8').lower())
      
    # # Переопределение функции преобразования к верхнему геристру
    # def sqlite_upper(self, value_):
    #     return value_.upper()
    #       