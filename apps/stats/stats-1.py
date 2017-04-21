##########################################################################
#
#  Copyright (c) 2016, Image Engine Design Inc. All rights reserved.
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are
#  met:
#
#      * Redistributions of source code must retain the above
#        copyright notice, this list of conditions and the following
#        disclaimer.
#
#      * Redistributions in binary form must reproduce the above
#        copyright notice, this list of conditions and the following
#        disclaimer in the documentation and/or other materials provided with
#        the distribution.
#
#      * Neither the name of John Haddon nor the names of
#        any other contributors to this software may be used to endorse or
#        promote products derived from this software without specific prior
#        written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
#  IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
#  THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
#  PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
#  CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
#  EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
#  PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
#  PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
#  LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
#  NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
#  SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
##########################################################################

import os
import gc
import sys
import time
import resource
import collections

import IECore

import Gaffer

class stats( Gaffer.Application ) :

	def __init__( self ) :

		Gaffer.Application.__init__(
			self,
			"""
			Outputs statistics about a Gaffer script, including the version of
			Gaffer that created it, the values of all setting and variables and
			the types of node in use. May also be used to perform performance
			analysis of image and scene processing nodes within the script, using
			a performance monitor to generate advanced statistics.

			To output basic information about a script :

			```
			gaffer stats fileName.gfr
			```

			To run a scene processing node using the performance monitor :

			```
			gaffer stats fileName.gfr -scene NameOfNode -performanceMonitor
			```

			To run an image processing node using the performance monitor :

			```
			gaffer stats fileName.gfr -image NameOfNode -performanceMonitor
			```
			"""
		)

		self.parameters().addParameters(

			[
				IECore.FileNameParameter(
					name = "script",
					description = "The script to examine.",
					defaultValue = "",
					allowEmptyString = False,
					extensions = "gfr",
					check = IECore.FileNameParameter.CheckType.MustExist,
				),

				IECore.FileNameParameter(
					name = "outputFile",
					description = "Output the results to this file on disk rather than stdout",
					defaultValue = "",
					allowEmptyString = True,
					extensions = "",
				),

				IECore.FloatParameter(
					name = "frame",
					description = "The frame to evaluate statistics at.",
					defaultValue = 1,
				),

				IECore.StringParameter(
					name = "scene",
					description = "The name of a SceneNode or ScenePlug to examine.",
					defaultValue = "",
				),

				IECore.StringParameter(
					name = "image",
					description = "The name of an ImageNode or ImagePlug to examine.",
					defaultValue = "",
				),

				IECore.BoolParameter(
					name = "performanceMonitor",
					description = "Turns on a performance monitor to provide additional"
						"statistics about the operation of the node graph.",
					defaultValue = False,
				),

				IECore.IntParameter(
					name = "maxLinesPerMetric",
					description = "The maximum number of plugs to list for each metric "
						"captured by the performance monitor.",
					defaultValue = 50,
				),

				IECore.BoolParameter(
					name = "contextMonitor",
					description = "Turns on a context monitor to provide additional "
						"statistics about the operation of the node graph.",
					defaultValue = False,
				),

				IECore.StringParameter(
					name = "contextMonitorRoot",
					description = "The name of a node or plug to provide a root for the "
						"context monitor. Statistics will only be captured for this root "
						"downwards.",
					defaultValue = "",
				)

			]

		)

		self.parameters().userData()["parser"] = IECore.CompoundObject(
			{
				"flagless" : IECore.StringVectorData( [ "script" ] )
			}
		)

	def _run( self, args ) :

		self.__timers = collections.OrderedDict()
		self.__memory = collections.OrderedDict()

		self.__memory["Application"] = _Memory.maxRSS()

		script = Gaffer.ScriptNode()
		script["fileName"].setValue( os.path.abspath( args["script"].value ) )

		with _Timer() as loadingTimer :
			script.load( continueOnError = True )
		self.__timers["Loading"] = loadingTimer

		self.__memory["Script"] = _Memory.maxRSS() - self.__memory["Application"]

		if args["performanceMonitor"].value :
			self.__performanceMonitor = Gaffer.PerformanceMonitor()
		else :
			self.__performanceMonitor = None

		if args["contextMonitor"].value :
			contextMonitorRoot = None
			if args["contextMonitorRoot"].value :
				contextMonitorRoot = script.descendant( args["contextMonitorRoot"].value )
				if contextMonitorRoot is None :
					IECore.msg( IECore.Msg.Level.Error, "stats", "Context monitor root \"%s\" does not exist" % args["contextMonitorRoot"].value )
					return 1
			self.__contextMonitor = Gaffer.ContextMonitor( contextMonitorRoot )
		else :
			self.__contextMonitor = None

		self.__output = file( args["outputFile"].value, "w" ) if args["outputFile"].value else sys.stdout
		
		with Gaffer.Context( script.context() ) as context :

			context.setFrame( args["frame"].value )

			self.__writeVersion( script )

			self.__output.write( "\n" )

			self.__writeArgs( args )

			self.__output.write( "\n" )

			self.__writeSettings( script )

			self.__output.write( "\n" )

			self.__writeVariables( script )

			self.__output.write( "\n" )

			self.__writeNodes( script )

			if args["scene"].value :

				self.__writeScene( script, args )

			if args["image"].value :

				self.__writeImage( script, args )

		self.__output.write( "\n" )

		self.__writeMemory()

		self.__output.write( "\n" )

		self.__writePerformance( script, args )

		self.__output.write( "\n" )

		self.__writeContext( script, args )

		self.__output.write( "\n" )

		self.__output.close()
		
		return 0

	def __writeVersion( self, script ) :

		numbers = [ Gaffer.Metadata.nodeValue( script, "serialiser:" + x + "Version" ) for x in ( "milestone", "major", "minor", "patch" ) ]
		if None not in numbers :
			version = ".".join( str( x ) for x in numbers )
		else :
			version = "unknown"

		versions = (
			( "Script", version ),
			( "Current", Gaffer.About.versionString() ),
		)

		self.__output.write( "Gaffer Version :\n\n" )
		self.__writeItems( versions )

	def __writeItems( self, items ) :

		if not len( items ) :
			return

		width = max( [ len( x[0] ) for x in items ] ) + 4
		for name, value in items :
			self.__output.write( "  {name:<{width}}{value}\n".format( name = name, width = width, value = value ) )

	def __writeArgs( self, args ) :

		self.__output.write( "Args :\n\n" )
		self.__writeItems( args.items() )

	def __writeSettings( self, script ) :

		plugsToIgnore = {
			script["fileName"],
			script["unsavedChanges"],
			script["variables"],
		}

		items = []
		def itemsWalk( p ) :

			if p in plugsToIgnore :
				return

			if hasattr( p, "getValue" ) :
				items.append( ( p.relativeName( script ), p.getValue() ) )
			else :
				for c in p.children( Gaffer.Plug ) :
					itemsWalk( c )

		itemsWalk( script )

		self.__output.write( "Settings :\n\n" )
		self.__writeItems( items )

	def __writeVariables( self, script ) :

		items = []
		for p in script["variables"] :
			data, name = script["variables"].memberDataAndName( p )
			if data is not None :
				items.append( ( name, data ) )

		self.__output.write( "Variables :\n\n" )
		self.__writeItems( items )

	def __writeNodes( self, script ) :

		def countWalk( node, counter ) :

			if not isinstance( node, Gaffer.ScriptNode ) :
				counter[node.typeName()] += 1

			for c in node.children( Gaffer.Node ) :
				countWalk( c, counter )

		counter = collections.Counter()
		countWalk( script, counter )

		items = [ ( nodeType.rpartition( ":" )[2], count ) for nodeType, count in counter.most_common() ]
		items.extend( [
			( "", "" ),
			( "Total", sum( counter.values() ) ),
		] )

		self.__output.write( "Nodes :\n\n" )
		self.__writeItems( items )

	def __writeScene( self, script, args ) :

		import GafferScene
		import GafferSceneTest

		scene = script.descendant( args["scene"].value )
		if isinstance( scene, Gaffer.Node ) :
			scene = next( ( x for x in scene.children( GafferScene.ScenePlug ) ), None )

		if scene is None :
			IECore.msg( IECore.Msg.Level.Error, "stats", "Scene \"%s\" does not exist" % args["scene"].value )
			return

		memory = _Memory.maxRSS()
		with _Timer() as sceneTimer :
			with self.__performanceMonitor or _NullContextManager(), self.__contextMonitor or _NullContextManager() :
				GafferSceneTest.traverseScene( scene )
		self.__timers["Scene generation"] = sceneTimer
		self.__memory["Scene generation"] = _Memory.maxRSS() - memory

		## \todo Calculate and write scene stats
		#  - Locations
		#  - Unique objects, attributes etc

	def __writeImage( self, script, args ) :

		import GafferImage
		import GafferImageTest

		image = script.descendant( args["image"].value )
		if isinstance( image, Gaffer.Node ) :
			image = next( ( x for x in image.children( GafferImage.ImagePlug ) ), None )

		if image is None :
			IECore.msg( IECore.Msg.Level.Error, "stats", "Image \"%s\" does not exist" % args["image"].value )
			return

		memory = _Memory.maxRSS()
		with _Timer() as imageTimer :
			with self.__performanceMonitor or _NullContextManager(), self.__contextMonitor or _NullContextManager() :
				GafferImageTest.processTiles( image )
		self.__timers["Image generation"] = imageTimer
		self.__memory["Image generation"] = _Memory.maxRSS() - memory
		self.__memory["OIIO cache limit"] = _Memory( GafferImage.OpenImageIOReader.getCacheMemoryLimit() )
		self.__memory["OIIO cache usage"] = _Memory( GafferImage.OpenImageIOReader.cacheMemoryUsage() )

		items = [
			( "Format", image["format"].getValue() ),
			( "Data window", image["dataWindow"].getValue() ),
			( "Channel names", image["channelNames"].getValue() ),
		]

		self.__output.write( "\nImage :\n\n" )
		self.__writeItems( items )

	def __writeMemory( self ) :

		objectPool = IECore.ObjectPool.defaultObjectPool()

		items = self.__memory.items()

		items.extend( [
			( "", "" ),
			( "Cache limit", _Memory( Gaffer.ValuePlug.getCacheMemoryLimit() ) ),
			( "Cache usage", _Memory( Gaffer.ValuePlug.cacheMemoryUsage() ) ),
			( "", "" ),
			( "Object pool limit", _Memory( objectPool.getMaxMemoryUsage() ) ),
			( "Object pool usage", _Memory( objectPool.memoryUsage() ) ),
			( "", "" ),
			( "Max resident size", _Memory.maxRSS() ),
		] )

		self.__output.write( "Memory :\n\n" )
		self.__writeItems( items )

	def __writeStatisticsItems( self, script, stats, key, n ) :

		stats.sort( key = key, reverse = True )
		items = [ ( x[0].relativeName( script ), key( x ) ) for x in stats[:n] ]
		self.__writeItems( items )

	def __writePerformance( self, script, args ) :

			self.__output.write( "Performance :\n\n" )
			self.__writeItems( self.__timers.items() )

			if self.__performanceMonitor is not None :
				self.__output.write(
					"\n" + Gaffer.MonitorAlgo.formatStatistics(
						self.__performanceMonitor,
						maxLinesPerMetric = args["maxLinesPerMetric"].value
					)
				)

	def __writeContext( self, script, args ) :

			if self.__contextMonitor is None :
				return

			self.__output.write( "Contexts :\n\n" )

			stats = self.__contextMonitor.combinedStatistics()

			items = [ ( n, stats.numUniqueValues( n ) ) for n in stats.variableNames() ]
			items += [
				( "", "" ),
				( "Unique contexts", stats.numUniqueContexts() ),
			]

			self.__writeItems( items )

class _Timer( object ) :

	def __enter__( self ) :

		self.__time = time.time()
		self.__clock = time.clock()

		return self

	def __exit__( self, type, value, traceBack ) :

		self.__time = time.time() - self.__time
		self.__clock = time.clock() - self.__clock

	def __str__( self ) :

		return "%.3fs (wall), %.3fs (CPU)" % ( self.__time, self.__clock )

class _Memory( object ) :

	def __init__( self, bytes ) :

		self.__bytes = bytes

	@classmethod
	def maxRSS( cls ) :

		if sys.platform == "darwin" :
			return cls( resource.getrusage( resource.RUSAGE_SELF ).ru_maxrss )
		else :
			return cls( resource.getrusage( resource.RUSAGE_SELF ).ru_maxrss * 1024 )

	def __str__( self ) :

		return "%.3fM" % ( self.__bytes / ( 1024 * 1024. ) )

	def __sub__( self, other ) :

		return _Memory( self.__bytes - other.__bytes )

class _NullContextManager( object ) :

	def __enter__( self ) :

		pass

	def __exit__( self, type, value, traceBack ) :

		pass

IECore.registerRunTimeTyped( stats )
