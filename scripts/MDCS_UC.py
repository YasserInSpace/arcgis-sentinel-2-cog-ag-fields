# ------------------------------------------------------------------------------
# Copyright 2021 Esri
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ------------------------------------------------------------------------------
# Name: MDCS_UC.py
# Description: A class to implement all user functions or to extend the built in MDCS functions/commands chain.
# Version: 20210211
# Requirements: ArcGIS 10.1 SP1
# Author: Esri Imagery Workflows team
# ------------------------------------------------------------------------------
#!/usr/bin/env python
import os
import sys
import arcpy
from datetime import datetime
from datetime import timedelta
import subprocess
import urllib
import json
import csv
import requests
#from satsearch import Search
from pystac_client import Client
from typing import Any, Dict


class UserCode:

    def __init__(self):
        pass    # initialize variables that need to be shared between multiple user commands.

    def sample00(self, data):
        base = data['base']         # using Base class for its XML specific common functions. (getXMLXPathValue, getXMLNodeValue, getXMLNode)
        xmlDOM = data['mdcs']       # access to MDCS config file
        command_used = base.getXMLNodeValue(xmlDOM, 'Command')
        workspace = data['workspace']
        md = data['mosaicdataset']
        log = data['log']
        log.Message('%s\\%s' % (workspace, md), 0)
        return True

    def sample01(self, data):
        log = data['log']           # How to use logging within the user function.
        log.Message('hello world', 0)
        return True

    def sample02(self, data):
        log = data['log']           # How to use logging within the user function.
        log.Message('Returning multiple values', 0)
        data['useResponse'] = True
        data['response'] = ['msg0', 'msg1', 'msg2']
        data['status'] = True   # overall function status
        return True    # True must be returned if data['useResponse'] is required. data['response'] can be used to return multiple values.

    def customCV(self, data):
        workspace = data['workspace']
        md = data['mosaicdataset']
        ds = os.path.join(workspace, md)
        fields = ['MinPS', 'MaxPS', 'WRS_Path', 'WRS_Row', 'AcquisitionDate', 'GroupName', 'Tag', 'PR', 'Month', 'DayOfYear', 'Name']
        print('Calculating values..')
        try:
            with arcpy.da.UpdateCursor(ds, fields) as cursor:
                for row in cursor:
                    row[0] = 0    # MinPS
                    row[1] = 300  # MaxPS
                    wrs_path = row[2]
                    wrs_row  = row[3]
                    if wrs_path is not None and wrs_row is not None:
                        row[7] = (wrs_path * 1000) + wrs_row  # PR
                    acq_date = row[4]
                    if acq_date is not None:
                        acq_str = str(acq_date).replace('-', '/')
                        row[8] = int(acq_str.split()[0].split('/')[1])  # Month
                    grp_name = row[5]
                    if grp_name is not None:
                        CMAX_INDEX = 16
                        if len(grp_name) >= CMAX_INDEX:
                            row[9]  = int(grp_name[13:CMAX_INDEX])  # DayOfYear
                            row[10] = grp_name.split('_')[0] + '_' + str(row[6])  # Name
                    cursor.updateRow(row)
        except arcpy.ExecuteError:
            data['log'].Message(arcpy.GetMessages(2), data['log'].const_critical_text)
    # create featureClass
    def createFeatureClass(self, data, workSpace, gdb, name):
        log = data['log']
        wrkSpace = os.path.join(workSpace, gdb)
        try:
            if not os.path.exists(wrkSpace):
                log.Message("Creating Database for Feature Class " + os.path.basename(wrkSpace) + "...", log.const_general_text)
                arcpy.management.CreateFileGDB(os.path.dirname(wrkSpace), os.path.basename(wrkSpace), "CURRENT")

            sr = arcpy.SpatialReference(3857)
            arcpy.management.CreateFeatureclass(wrkSpace, name, "POLYGON",
                                                spatial_reference=sr,
                                                has_m="DISABLED", has_z="DISABLED")

            return os.path.join(wrkSpace, name)

        except arcpy.ExecuteError:
            log.Message(arcpy.GetMessages(2), log.const_critical_text)
            return False
        except Exception as exp:
            log.Message(str(exp), log.const_critical_text)
            return False


    def addFieldsMasterFC(self, data, featClass, fld_lst):
        log = data['log']
        # (field_name, field_type, field_length)  — None length = not applicable
        field_defs = [
            (fld_lst[1],  'DATE',  None),   # AcquisitionDate
            (fld_lst[2],  'FLOAT', None),   # CloudCover
            (fld_lst[3],  'TEXT',  180),    # Name
            (fld_lst[4],  'TEXT',  400),    # ProductID
            (fld_lst[5],  'TEXT',  180),    # ProductURL
            (fld_lst[6],  'TEXT',  180),    # Constellation
            (fld_lst[7],  'TEXT',  6),      # SRS
            (fld_lst[8],  'LONG',  None),   # NumDate
            (fld_lst[9],  'TEXT',  80),     # Tile_BB_Values
            (fld_lst[10], 'TEXT',  80),     # RasterProxy_BB_Values
            (fld_lst[11], 'LONG',  None),   # Q
            (fld_lst[12], 'LONG',  None),   # Best
        ]
        try:
            log.Message("Adding Field to " + os.path.basename(featClass) + "...", log.const_general_text)
            for fld_name, fld_type, fld_len in field_defs:
                kwargs = {'field_type': fld_type}
                if fld_len is not None:
                    kwargs['field_length'] = fld_len
                try:
                    arcpy.management.AddField(featClass, fld_name, **kwargs)
                except arcpy.ExecuteError:
                    log.Message(arcpy.GetMessages(2), log.const_critical_text)
                    log.Message("\tSkipping field; not valid for this product.", log.const_general_text)
            return True
        except Exception as exp:
            log.Message(str(exp), log.const_critical_text)
            return False

    def addFields(self, data, featClass, fld_lst):
        log = data['log']
        # (field_name, field_type, field_length)  — None length = not applicable
        field_defs = [
            (fld_lst[1],  'DATE',  None),   # AcquisitionDate
            (fld_lst[2],  'FLOAT', None),   # CloudCover
            (fld_lst[3],  'TEXT',  200),    # ID
            (fld_lst[4],  'TEXT',  400),    # ProductID
            (fld_lst[5],  'TEXT',  180),    # Constellation
            (fld_lst[6],  'TEXT',  6),      # SRS
            (fld_lst[7],  'LONG',  None),   # NumDate
            (fld_lst[8],  'LONG',  None),   # Q
            (fld_lst[9],  'LONG',  None),   # Best
            (fld_lst[10], 'TEXT',  5000),   # Raster
            (fld_lst[11], 'TEXT',  10),     # Tag
        ]
        try:
            log.Message("Adding Field to " + os.path.basename(featClass) + "...", log.const_general_text)
            for fld_name, fld_type, fld_len in field_defs:
                kwargs = {'field_type': fld_type}
                if fld_len is not None:
                    kwargs['field_length'] = fld_len
                try:
                    arcpy.management.AddField(featClass, fld_name, **kwargs)
                except arcpy.ExecuteError:
                    log.Message(arcpy.GetMessages(2), log.const_critical_text)
                    log.Message("\tSkipping field; not valid for this product.", log.const_general_text)
            return True
        except Exception as exp:
            log.Message(str(exp), log.const_critical_text)
            return False


    def embedMRF(self,data,cache_loc,tile_string,maxX,maxY,minX,minY,srs_string,bands):
        log = data['log']
        try:
            tile_url = cache_loc + tile_string[55:]
            cache_path = os.path.join(tile_url,bands)
            bandpath_amzn = tile_string+bands+".tif"
            if bands in ["B01","B09","AOT"]:
                try:
                    #create template for 10m resolution and write to a file
                    cachingMRF = \
                            '<MRF_META>\n'  \
                            '  <CachedSource>\n'  \
                            '    <Source>/vsicurl/{0}</Source>\n'  \
                            '  </CachedSource>\n'  \
                            '  <Raster>\n'  \
                            '    <Size c="1" x="1830" y="1830"/>\n'  \
                            '    <PageSize c="1" x="512" y="512"/>\n'  \
                            '    <Compression>LERC</Compression>\n'  \
                            '    <DataType>UInt16</DataType>\n'  \
                            '  <DataFile>{1}.mrf_cache</DataFile><IndexFile>{1}.mrf_cache</IndexFile></Raster>\n'  \
                            '  <Rsets model="uniform" scale="2"/>\n'  \
                            '  <GeoTags>\n'  \
                            '    <BoundingBox maxx="{2}" maxy="{3}" minx="{4}" miny="{5}"/>\n'  \
                            '    <Projection>{6}</Projection>\n'  \
                            '  </GeoTags>\n'  \
                            '  <Options>V2=ON</Options>\n'  \
                            '</MRF_META>\n'.format(bandpath_amzn,cache_path,maxX,maxY,minX,minY,srs_string)

                except Exception as exp:
                    log.Message(str(exp),log.const_critical_text)

            elif bands in ["B05","B06","B07","B8A","B11","B12","SCL"]:
                try:
                    #template for 20m resolution and write to a file
                    cachingMRF= \
                            '<MRF_META>\n'  \
                            '  <CachedSource>\n'  \
                            '    <Source>/vsicurl/{0}</Source>\n'  \
                            '  </CachedSource>\n'  \
                            '  <Raster>\n'  \
                            '    <Size c="1" x="5490" y="5490"/>\n'  \
                            '    <PageSize c="1" x="512" y="512"/>\n'  \
                            '    <Compression>LERC</Compression>\n'  \
                            '    <DataType>UInt16</DataType>\n'  \
                            '  <DataFile>{1}.mrf_cache</DataFile><IndexFile>{1}.mrf_cache</IndexFile></Raster>\n'  \
                            '  <Rsets model="uniform" scale="2"/>\n'  \
                            '  <GeoTags>\n'  \
                            '    <BoundingBox maxx="{2}" maxy="{3}" minx="{4}" miny="{5}"/>\n'  \
                            '    <Projection>{6}</Projection>\n'  \
                            '  </GeoTags>\n'  \
                            '  <Options>V2=ON</Options>\n'  \
                            '</MRF_META>\n'.format(bandpath_amzn,cache_path,maxX,maxY,minX,minY,srs_string)

                except Exception as exp:
                    log.Message(str(exp),log.const_critical_text)

            else:
                try:
                    #template for 60m resolution and write to a file
                    cachingMRF = \
                            '<MRF_META>\n'  \
                            '  <CachedSource>\n'  \
                            '    <Source>/vsicurl/{0}</Source>\n'  \
                            '  </CachedSource>\n'  \
                            '  <Raster>\n'  \
                            '    <Size c="1" x="10980" y="10980"/>\n'  \
                            '    <PageSize c="1" x="512" y="512"/>\n'  \
                            '    <Compression>LERC</Compression>\n'  \
                            '    <DataType>UInt16</DataType>\n'  \
                            '  <DataFile>{1}.mrf_cache</DataFile><IndexFile>{1}.mrf_cache</IndexFile></Raster>\n'  \
                            '  <Rsets model="uniform" scale="2"/>\n'  \
                            '  <GeoTags>\n'  \
                            '    <BoundingBox maxx="{2}" maxy="{3}" minx="{4}" miny="{5}"/>\n'  \
                            '    <Projection>{6}</Projection>\n'  \
                            '  </GeoTags>\n'  \
                            '  <Options>V2=ON</Options>\n'  \
                            '</MRF_META>\n'.format(bandpath_amzn,cache_path,maxX,maxY,minX,minY,srs_string)

                except Exception as exp:
                    log.Message(str(exp),2)

            return cachingMRF

        except Exception as exp:
            log.Message(str(exp),2)

    def findBestTiles(self, data, input_fc):
        log = data['log']
        SENTINEL2_TILE_AREA_KM2 = 12115.0  # reference full-tile area in km²
        fields = ['AcquisitionDate', 'CloudCover', 'Q', 'Shape_Area', 'Best']
        log.Message("Calculating the Q and Best value...", 0)
        try:
            with arcpy.da.UpdateCursor(input_fc, fields) as cursor:
                for row in cursor:
                    acq_date = str(row[0]).replace('-', '/')
                    parts = acq_date.split()[0].split('/')
                    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                    cc = row[1] if row[1] is not None else 0
                    cloud_penalty = (cc / 100.0) * 180
                    date_diff = datetime(year, month, day) - datetime(1899, 12, 31)
                    date_float = float(date_diff.days) + (float(date_diff.seconds) / 86400)
                    area_km2 = row[3] / 1_000_000
                    area_ratio = area_km2 / SENTINEL2_TILE_AREA_KM2
                    if 0.2 < area_ratio <= 1.0:
                        area_penalty = -(60 - area_ratio * 60)
                    elif area_ratio <= 0.2:
                        area_penalty = -(600 - area_ratio * 600)
                    else:
                        area_penalty = 0
                    q = (100000 - date_float + cloud_penalty) - area_penalty
                    row[2] = q
                    row[4] = q
                    cursor.updateRow(row)
        except arcpy.ExecuteError:
            log.Message(arcpy.GetMessages(2), 3)
            return False
        except Exception as exp:
            log.Message(str(exp), 3)
            return False


    def readJson(self, data, url):
        log = data['log']
        jsonValList = []

        try:
            response = urllib.request.urlopen(url)

            jsData = json.loads(response.read())

            # A list of features and coordinate pairs
            feature_info = jsData['geometry']['coordinates']

            # A list that will hold each of the Polygon objects
            features = []

            wgs_sr = arcpy.SpatialReference(4326)


            # Create Polygon objects based an the array of points
            for feature in feature_info:
                array = arcpy.Array([arcpy.Point(*coords) for coords in feature])
                    # Add the first coordinate pair to the end to close polygon
                array.append(array[0])

            features=arcpy.Polygon(array,wgs_sr)
            # features.projectAs(wm_sr)
            jsonValList.append(features)


            AcquisitionDate = jsData['properties']['datetime']
            AcquisitionDate = AcquisitionDate[0:10]+' '+AcquisitionDate[11:19]

            jsonValList.append(AcquisitionDate)

            cloudcover = jsData['properties']['eo:cloud_cover']
            jsonValList.append(cloudcover)

            ProductName = jsData['id']
            jsonValList.append(ProductName)

            Productid = jsData['properties']['sentinel:product_id']
            jsonValList.append(Productid)

            #ProductURL = "http://sentinel-cogs.s3-us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/" + ProductName[4:6]+'/'+ProductName[6]+'/'+ProductName[7:9]+'/'+ProductName[10:14]+'/'+str(int(ProductName[14:16]))+'/'+ProductName+'/'
            ProductURL = (jsData['assets']['visual']['href'])[:-7]
            jsonValList.append(ProductURL)

            Constellation  = jsData['properties']['constellation']
            jsonValList.append(Constellation)

            srs  = jsData['properties'].get('proj:epsg') or int(jsData['properties'].get('proj:code', '0').replace('EPSG:', ''))
            jsonValList.append(srs)



            NumDate  = AcquisitionDate[0:4]+AcquisitionDate[5:7]+AcquisitionDate[8:10]
            jsonValList.append(NumDate)

            min_X = str(jsData['bbox'][0])
            min_Y = str(jsData['bbox'][1])
            max_X = str(jsData['bbox'][2])
            max_Y = str(jsData['bbox'][3])
            Tile_BB_Values = min_X + ","+ min_Y + ","+ max_X + ","+ max_Y
            jsonValList.append(Tile_BB_Values)


            Shape = jsData['assets']['visual']['proj:shape'][0]
            min_X = jsData['assets']['visual']['proj:transform'][2]
            max_Y = jsData['assets']['visual']['proj:transform'][5]
            Multipliers = jsData['assets']['visual']['proj:transform'][0]

            max_X = min_X + Shape * Multipliers
            min_Y = max_Y - Shape * Multipliers


            RasterProxy_BB_Values = str(max_X) + ","+ str(max_Y) + ","+ str(min_X) + ","+ str(min_Y)
            jsonValList.append(RasterProxy_BB_Values)


            Q = 42572
            jsonValList.append(Q)

            Best = 542572
            jsonValList.append(Best)



            del AcquisitionDate,cloudcover,ProductName,ProductURL,srs,NumDate,Tile_BB_Values
            del jsData,wgs_sr

            return jsonValList

        except Exception as exp:
            log.Message(str(exp),2)
            log.Message(("Unable to create a valid json_Val_List for {}..Moving to the next grid".format(url)),2)
            return False


    def readStac(self, data, stac):
        log = data['log']
        jsonValList = []

        try:

            jsData = stac

            # A list of features and coordinate pairs
            feature_info = jsData.geometry['coordinates']

            # A list that will hold each of the Polygon objects
            features = []

            wgs_sr = arcpy.SpatialReference(4326)


            # Create Polygon objects based an the array of points
            for feature in feature_info:
                array = arcpy.Array([arcpy.Point(*coords) for coords in feature])
                    # Add the first coordinate pair to the end to close polygon
                array.append(array[0])

            features=arcpy.Polygon(array,wgs_sr)
            # features.projectAs(wm_sr)
            jsonValList.append(features)


            AcquisitionDate = jsData.properties['datetime']
            AcquisitionDate = AcquisitionDate[0:10]+' '+AcquisitionDate[11:19]

            jsonValList.append(AcquisitionDate)

            cloudcover = jsData.properties['eo:cloud_cover']
            jsonValList.append(cloudcover)

            ProductName = jsData.id
            jsonValList.append(ProductName)

            Productid = jsData.properties['s2:product_uri']
            jsonValList.append(Productid)

            #ProductURL = "http://sentinel-cogs.s3-us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/" + ProductName[4:6]+'/'+ProductName[6]+'/'+ProductName[7:9]+'/'+ProductName[10:14]+'/'+str(int(ProductName[14:16]))+'/'+ProductName+'/'
            ProductURL = (jsData.assets['visual'].href)[:-7]
            jsonValList.append(ProductURL)

            Constellation  = jsData.properties['constellation']
            jsonValList.append(Constellation)

            srs  = jsData.properties.get('proj:epsg') or int(jsData.properties.get('proj:code', '0').replace('EPSG:', ''))
            jsonValList.append(srs)



            NumDate  = AcquisitionDate[0:4]+AcquisitionDate[5:7]+AcquisitionDate[8:10]
            jsonValList.append(NumDate)

            min_X = str(jsData.bbox[0])
            min_Y = str(jsData.bbox[1])
            max_X = str(jsData.bbox[2])
            max_Y = str(jsData.bbox[3])
            Tile_BB_Values = min_X + ","+ min_Y + ","+ max_X + ","+ max_Y
            jsonValList.append(Tile_BB_Values)


            Shape = jsData.assets['visual'].extra_fields['proj:shape'][0]
            min_X = jsData.assets['visual'].extra_fields['proj:transform'][2]
            max_Y = jsData.assets['visual'].extra_fields['proj:transform'][5]
            Multipliers = jsData.assets['visual'].extra_fields['proj:transform'][0]

            max_X = min_X + Shape * Multipliers
            min_Y = max_Y - Shape * Multipliers


            RasterProxy_BB_Values = str(max_X) + ","+ str(max_Y) + ","+ str(min_X) + ","+ str(min_Y)
            jsonValList.append(RasterProxy_BB_Values)


            Q = 42572
            jsonValList.append(Q)

            Best = 542572
            jsonValList.append(Best)



            del AcquisitionDate,cloudcover,ProductName,ProductURL,srs,NumDate,Tile_BB_Values
            del jsData,wgs_sr

            return jsonValList

        except Exception as exp:
            log.Message(str(exp),2)
            log.Message(("Unable to create a valid json ...Moving to the next grid"),2)
            return False


    def date_range(self, data,start, end, intv):
        log = data['log']
        datelist =[]
        try:
            start = datetime.strptime(start,"%Y-%m-%d").date()
            end = datetime.strptime(end,"%Y-%m-%d").date()
            diff = (end-start)//int(intv)
            for i in range(int(intv)):
                startdate = ((start + diff * i).strftime("%Y-%m-%d"))
                endDate = ((start + diff * (i+1)).strftime("%Y-%m-%d"))
                datelist.append(startdate+'/'+endDate)
            return datelist
            
        except Exception as exp:
            log.Message(str(exp),2)
            log.Message(("Unable to create a valid date range"),2)
            return False


    def sentinelModifySrc(self, data):
        log = data['log']
        base = data['base']         # using Base class for its XML specific common functions. (getXMLXPathValue, getXMLNodeValue, getXMLNode)
        xmlDOM = data['mdcs']

        paramPath = base.const_import_geometry_features_path_
        bandFc = os.path.join(paramPath,'BandFC')
        masterFc = os.path.join(paramPath,'MasterFC')
        jsonPath = os.path.join(paramPath,'Json')
        CSVPath = os.path.join(paramPath,'csv')
        file = open(os.path.join(CSVPath, "sample.csv"), 'w+', newline ='')
        file.close()

        # user imported data
        curryear=datetime.now().year
        currmonth=datetime.now().month
        currday=datetime.now().day


        # user imported data
        CSV_path = base.getXMLNodeValue(xmlDOM, 'CSV_path')
        startDate = base.getXMLNodeValue(xmlDOM, 'startDate')
        endDate = base.getXMLNodeValue(xmlDOM, 'endDate')
        interval = base.getXMLNodeValue(xmlDOM, 'interval')
        cloudePercentage = base.getXMLNodeValue(xmlDOM, 'cloud')
        coordinateInput = base.getXMLNodeValue(xmlDOM, 'coordinate')
        bestSceneOnly = base.getXMLNodeValue(xmlDOM, 'best_scene_only')
        bestSceneOnly = (str(bestSceneOnly).strip() == '1')
        mrfCache = base.getXMLNodeValue(xmlDOM, 'mrf_cache')
        if mrfCache == '#':
            mrfCache = 'C:/mrfcache/cachingmrf'
        mrfCache = mrfCache.rstrip('/') + '/'
        monthsInput = base.getXMLNodeValue(xmlDOM, 'months')
        if monthsInput == '#' or monthsInput.strip() == '':
            allowedMonths = []
        else:
            allowedMonths = [int(m.strip()) for m in monthsInput.split(',') if m.strip().isdigit()]
        

        if coordinateInput == "#":
            coordinateList = [-110,39.5,-105,40.5]
        else:
            coordinateList = coordinateInput.split(",")
            for i in range(0, len(coordinateList)):
                coordinateList[i] = float(coordinateList[i])



        if interval == "#":
            dateInterval = 1
        else:
            dateInterval = interval


        
        datelist = self.date_range(data, startDate, endDate, dateInterval)
      

        

        # if startDate == "#" or endDate == "#":
        #     start_date = (datetime(curryear, currmonth, currday)-timedelta(days=100)).strftime('%Y-%m-%dT%H:%M:%SZ')
        #     end_date = (datetime(curryear, currmonth, currday)-timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        #     #make the end date as 1 day minus todays date
        # else:
        #     start_date = (datetime(int(startDate[0:4]), int(startDate[5:7]), int(startDate[8:10]))).strftime('%Y-%m-%dT%H:%M:%SZ')
        #     end_date = (datetime(int(endDate[0:4]), int(endDate[5:7]), int(endDate[8:10]))).strftime('%Y-%m-%dT%H:%M:%SZ')


        # daterequest = str(start_date)+"/"+str(end_date)



        # url = 'https://earth-search.aws.element84.com/v0/search'
        # query_params = {
        #     "collections": ["sentinel-s2-l2a-cogs"],
        #     "bbox": coordinateList,
        #     "query": {
        #     "eo:cloud_cover": {
        #     "lt": int(cloudePercentage)
        #     }},
        #     "datetime": daterequest,
        #     "limit": 5000,
        # }

        
        # responseData=requests.post(url,json=query_params)
        # responseData = responseData.json()

        # urlList = []
        # for i in range(len(responseData['features'])):
        #     hreflist = []
        #     hreflist.append(responseData['features'][i]['links'][1]['href'])
        #     urlList.append(hreflist)

        # opening the csv file in 'w+' mode
        

        # writing the data into the file
        # with file:
        #     write = csv.writer(file)
        #     write.writerows(urlList)

        # if CSV_path == "#":
        #     CSV_path = os.path.join(CSVPath, "sample.csv")


        # Column for master feature class
        field_list_Master_FC=['SHAPE@','AcquisitionDate','CloudCover','Name','ProductID','ProductURL','Constellation','SRS',"NumDate",'Tile_BB_Values','RasterProxy_BB_Values','Q','Best']
        try :
            arcpy.env.overwriteOutput=True
            featureclassFullPath = self.createFeatureClass(data,masterFc,'MasterFC.gdb','MasterTiles')
            self.addFieldsMasterFC(data,featureclassFullPath,field_list_Master_FC[0:])

        except Exception as exp:
            log.Message(str(exp),2)


        with arcpy.da.InsertCursor(featureclassFullPath, field_list_Master_FC) as cursor:
            if CSV_path != "#":
                if CSV_path.lower().endswith('.csv'):
                    try:
                        with open(CSV_path) as csv_file:
                            csv_reader = csv.reader(csv_file, delimiter=',')
                            for row in csv_reader:
                                for url in row:
                                    if url.startswith("https") or url.startswith("http"):
                                        if url.endswith('.json'):
                                            JsonData = self.readJson(data, url)
                                            if JsonData != False:
                                                try:
                                                    log.Message("adding to the feature class " + JsonData[3] + "...", log.const_general_text)
                                                    cursor.insertRow(JsonData)
                                                except arcpy.ExecuteError:
                                                    log.Message(arcpy.GetMessages(2), 2)
                                                except Exception as exp:
                                                    log.Message(str(exp), 2)
                    except Exception as exp:
                        log.Message(str(exp), 2)
                else:
                    log.Message("File provided " + CSV_path + " is Incorrect. It should be CSV", 2)
                    log.Message("Terminating the program", 2)
                    return False
            else:
                url = 'https://earth-search.aws.element84.com/v1'
                client = Client.open(url)
                collections = 'sentinel-2-l2a'
                query = {'eo:cloud_cover': {'lte': float(cloudePercentage)}}
                aoi_as_dict: Dict[str, Any] = {
                    "type": "Polygon",
                    "coordinates": [[
                        [coordinateList[0], coordinateList[1]],
                        [coordinateList[2], coordinateList[1]],
                        [coordinateList[2], coordinateList[3]],
                        [coordinateList[0], coordinateList[3]],
                        [coordinateList[0], coordinateList[1]]
                    ]]
                }
                for dateTime in datelist:
                    try:
                        search = client.search(
                            collections=collections,
                            intersects=aoi_as_dict,
                            datetime=dateTime,
                            query=query
                        )
                    except Exception as exp:
                        log.Message(str(exp), 2)
                        continue
                    try:
                        log.Message("adding to the feature class for interval " + dateTime + "...", log.const_general_text)
                        items_to_insert = list(search.items())

                        # Step 1: apply months filter first
                        if allowedMonths:
                            before = len(items_to_insert)
                            items_to_insert = [
                                item for item in items_to_insert
                                if int(item.properties.get('datetime', '')[5:7]) in allowedMonths
                            ]
                            log.Message("months filter: kept " + str(len(items_to_insert)) + " of " + str(before) + " scene(s)", 0)

                        # Step 2: from remaining scenes pick best per tile
                        if bestSceneOnly:
                            best_per_tile = {}
                            for item in items_to_insert:
                                try:
                                    parts = item.id.split('_')
                                    tile_id = parts[1] if len(parts) > 1 else item.id
                                    cc = item.properties.get('eo:cloud_cover', 100)
                                    dt = item.properties.get('datetime', '')
                                    if tile_id not in best_per_tile:
                                        best_per_tile[tile_id] = (cc, dt, item)
                                    else:
                                        prev_cc, prev_dt, _ = best_per_tile[tile_id]
                                        if cc < prev_cc or (cc == prev_cc and dt > prev_dt):
                                            best_per_tile[tile_id] = (cc, dt, item)
                                except Exception as exp:
                                    log.Message(str(exp), 2)
                            log.Message("best_scene_only: keeping " + str(len(best_per_tile)) + " scene(s) out of tile coverage", 0)
                            items_to_insert = [v[2] for v in best_per_tile.values()]

                        for item in items_to_insert:
                            JsonData = self.readStac(data, item)
                            if JsonData != False:
                                try:
                                    log.Message("adding to the feature class " + JsonData[3] + "...", log.const_general_text)
                                    cursor.insertRow(JsonData)
                                except arcpy.ExecuteError:
                                    log.Message(arcpy.GetMessages(2), 2)
                                except Exception as exp:
                                    log.Message(str(exp), 2)
                    except Exception as exp:
                        log.Message(str(exp), 2)

        field_list=['SHAPE@','AcquisitionDate','CloudCover','ID','ProductID','Constellation','SRS',"NumDate",'Q','Best','Raster','Tag']
        try:
            arcpy.env.overwriteOutput=True
            featureclass = self.createFeatureClass(data,bandFc,"BandFC.gdb",'BandTiles')
            self.addFields(data,featureclass,field_list[0:])


        except Exception as exp:
            log.Message(str(exp),2)


        try:
            wrkSpace = os.path.join(masterFc, "MasterFC.gdb")
            masterFC = os.path.join(wrkSpace, "MasterTiles")
            field_list_master = ['SHAPE@', 'AcquisitionDate', 'CloudCover', 'Name', 'ProductID', 'ProductURL',
                                 'Constellation', 'SRS', 'NumDate', 'Tile_BB_Values', 'RasterProxy_BB_Values', 'Q', 'Best']
            cache_loc = mrfCache

            try:
                self.findBestTiles(data, masterFC)
            except Exception as exp:
                log.Message(str(exp), 3)

            try:
                log.Message("adding band feature class ...", log.const_general_text)
                bands = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B11", "B12"]
                with arcpy.da.SearchCursor(masterFC, field_list_master) as sc:
                    with arcpy.da.InsertCursor(featureclass, field_list) as cursor:
                        for row in sc:
                            try:
                                base = [row[0], row[1], row[2], row[3], row[4],
                                        row[6], row[7], row[8], row[11], row[12]]
                                srs = 'EPSG:' + str(base[6])
                                coordinate = row[10].split(",")
                                for band in bands:
                                    datareq = base[:]
                                    cachingmrf = self.embedMRF(data, cache_loc, row[5],
                                                               coordinate[0], coordinate[1],
                                                               coordinate[2], coordinate[3],
                                                               srs, band)
                                    datareq.append(cachingmrf)
                                    datareq.append(band)
                                    try:
                                        cursor.insertRow(datareq)
                                    except arcpy.ExecuteError:
                                        log.Message(arcpy.GetMessages(2), 2)
                                    except Exception as exp:
                                        log.Message(str(exp), 2)
                            except Exception as exp:
                                log.Message(str(exp), 2)

                xmlDOM.getElementsByTagName("data_path")[0].firstChild.data = featureclass
                arcpy.env.overwriteOutput = False

            except arcpy.ExecuteError:
                log.Message(arcpy.GetMessages(2), 2)
            except Exception as exp:
                log.Message(str(exp), 2)

        except Exception as exp:
            log.Message(str(exp), 2)

        return True

    def markduplicate(self, data):
        log = data['log']
        workspace = data['workspace']
        md = data['mosaicdataset']
        try:
            ds = os.path.join(workspace, md)
            with arcpy.da.UpdateCursor(ds, ["Name", "Dataset_ID"], sql_clause=(None, 'ORDER BY Name')) as rows:
                value1 = 'gp'
                for row in rows:
                    try:
                        value = str(row[0])
                        if value == value1:
                            row[1] = 'dup'
                            rows.updateRow(row)
                        else:
                            value1 = value
                    except Exception as exp:
                        log.Message('failed to Update: ' + str(row[0]), 1)
        except arcpy.ExecuteError:
            log.Message(arcpy.GetMessages(2), 2)
            return False
        except Exception as exp:
            log.Message('markduplicate failed: ' + str(exp), 2)
            return False
        return True
