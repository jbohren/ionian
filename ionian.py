#!/usr/bin/python
'''
IONIAN - Rapid hierarchical file browsing.

TODO:	Configuration options
			Preferred editor
			Preferred control configuration
			Custom Color hilighting
			Different sorting schemes
			Make the path to root (/) is selected on open

CHANGELIST

1.1 General cleanup and greatly improved flicker
1.0 Initial Release

Copyright (c) 2008-2012, Jonathan Bohren ( me@jbohren.com )
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
3. Neither the name of Jonathan Bohren nor the names of its contributors may
   be used to endorse or promote products derived from this software without
   specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

'''

import os
import os.path
import stat
import statvfs
import time

import curses
import curses.wrapper
import curses.textpad

import locale
locale.setlocale(locale.LC_ALL,"")

import logging
LOG_FILENAME = './ionian.log'
logging.basicConfig(filename=LOG_FILENAME,level=logging.DEBUG)#NOTSET)

N_MIN_COLUMNS = 3
N_MIN_COL_WIDTH = 6

global env

class DefaultHandler():
	def process_char(self,ch):
		return ch

class VimHandler(DefaultHandler):
	def __init__(self):
		# Declare rules for normal mode
		self.normal_handlers = {
			':': self.handle_command,
		}

		# Declare rules for command mode
		self.command_identifiers = {
			'q': self.cmd_q,
			'e': self.cmd_e,
		}

	def process_char(self,ch):
		if self.normal_handlers.has_key(ch):
			self.capture_command(ch)
		return ch

	def no_action(self,ch):
		pass

	def capture_command(self,prompt_str):
		# Output the command prompt
		env.win_command.clear()
		env.win_command.addstr(0,0,prompt_str)
		env.win_command.noutrefresh()
		
		# Create a textpad for entering a command
		self.cmd_box = curses.textpad.Textbox(env.win_command)
		cmd_str = self.cmd_box.edit(self.input_validator)
		
		# Get the prompt
		prompt_str = cmd_str[0]
		
		# Call the correct handler
		self.normal_handlers.get(prompt_str,self.handler_not_found)(cmd_str)

	def input_validator(self,ch):
		return ch

	def handler_not_found(self,cmd_str):
		env.error("ERROR: Handler not found: \""+cmd_str[0]+"\"")

	def handle_command(self,cmd_str):
		# Get the command identifier
		cmd_str = cmd_str[1:]
		cmd = cmd_str.split(" ",1)
		
		self.command_identifiers.get(cmd[0],self.cmd_not_found)(cmd_str)

	# Commands
	def cmd_q(self,cmd_str):
		env.keep_running = False

	def cmd_e(self,cmd_str):
		os.system("vim " + env.viewer.get_selected_path())

	def cmd_not_found(self,cmd_str):
		env.error("ERROR: Command not found: \""+cmd_str[1:]+"\"")
		
	# Searching
	def handle_search(self,search_str):
		pass

class Column():
	def __init__(self,message_str=''):
		"""Base constructor"""
		self.is_enterable = False
		self.path = ""
		self.message_str = message_str

	def load(self, path):
		"""Base load, this jut sets the path to the path arg"""
		self.path = path

	def redraw(self,win):
		"""Redraw this column in the given window win"""
		self.win = win
		self.win.clear()
		[maxy, maxx] = self.win.getmaxyx()
		self.win.addnstr(1,1,self.message_str, maxx-3,curses.A_DIM)
		self.win.noutrefresh()

	def is_accessible(self,path):
		"""Checks if a file is accessible
		This performs a bunch of checks reuired to move into a directory
		The check sequence is important. If one check fails at one point,
		the following tests short and also fail.
		"""
		# Make sure the file exists
		exists = os.access(path,os.F_OK)

		# Make sure the file system is real... don't ask
		is_real = exists and os.statvfs(path)[statvfs.F_BLOCKS] > 0

		# Check for read privleges
		has_privleges = is_real and os.access(path,os.R_OK)

		return has_privleges

	def is_directory(self,path):
		"""Checks if path is a directory"""
		return os.path.isdir(path)

	def create_column(self,path):
		"""Creates a new column based on the kind of file"""
		if not self.is_accessible(path):
			logging.debug("EMPTY COL: "+path)
			return Column("NO ACCESS")
		elif self.is_directory(path):
			logging.debug("DIR COL: "+path)
			return Directory(path)
		else:
			logging.debug("TEXT COL: "+path)
			return Text(path)

# Text is a drawable column that shows the properties of a text file
class Text(Column):
	def __init__(self,path):
		self.load(path)
		self.is_enterable = False

	def load(self, path):
		"""Reads in the name of a plaintext file"""
		self.path = path
		self.name = path.split('/')[-1]

	def redraw(self,win):
		"""Redraw this window, and write the name of the file in it"""
		self.win = win
		self.win.clear()
		[maxy, maxx] = self.win.getmaxyx()
		self.win.addnstr(1,1,self.name, maxx-3,curses.A_DIM)
		self.win.noutrefresh()

# Directory is a drawable column that shows the contents of a directory
class Directory(Column):
	def __init__(self,path):
		self.is_enterable = True
		# Set selected and top indices
		self.selected = -1
		self.top = 0

		self.path = ""
		self.load(path)
	
	def load(self, path):
		"""Load the contents of the directory at this path"""
		if self.is_accessible(path):
			# First perform tests on path so that listdir doesn't block
			try:
				self.files = os.listdir(path)
				self.path = path
			except EnvironmentError:
				self.path = ''
				env.error("ERROR: Could not load directory \""+path+"\".")
		else:
			self.is_enterable = False

	def redraw(self,win):
		"""Redraw this directory column to the given window"""
		if self.path is not '':
			self.win = win
			self.load(self.path)

			# Clear this window
			self.win.clear()

			# Get size of this column
			[maxy, maxx] = self.win.getmaxyx()
			self.win.vline(0,maxx-1,curses.ACS_VLINE,maxy)

			# Check for emptiness
			if len(self.files) == 0:
				self.win.addnstr(1,1,"Empty Directory", maxx-3,curses.A_DIM)
				self.is_enterable = False
			else:
				# Iterate over the visible rows
				for r in range(maxy):
					style = curses.A_NORMAL
					# Get index of file for this row
					f = r + self.top
					if f < len(self.files):
						# Grab bool whether this is a directory or not
						is_dir = os.path.isdir(os.path.join(self.path,self.files[f]))

						# Invert colors if the row is selected
						if f == self.selected:
							style = curses.A_REVERSE
							self.win.hline(r,0,' ',maxx-1, style)

						# Hilight color if the row is a directory
						if is_dir:
							style = curses.color_pair(3)
							if f == self.selected:
								style = curses.color_pair(4)
								self.win.hline(r,0,' ',maxx-1, style)

						# Write the name of the file to the column
						logging.debug(self.files[f])
						self.win.addnstr(r,1,unicode(self.files[f],'ascii','ignore'), maxx-3,style)

						# Add a carat if the item is a directory
						if is_dir:
							self.win.addstr(r,maxx-3,'>',style)

			# Redraw the window
			self.win.noutrefresh()

	def select_rel(self,offset):
		"""Select an item by offset from the currently selected item"""
		return self.select_abs(self.selected+offset)

	def select_abs(self,index):
		"""Select a directory item by absolute index.
		This changes self.selected and updates self.top. It returns True if the
		selection is valid, False otherwise."""
		[maxy, maxx] = self.win.getmaxyx();

		if index < len(self.files) and index >= 0:
			self.selected = index

			# Reset the index of the item drawn at the top of the window
			if index - self.top > maxy -2:
				self.top = index - maxy + 2
			elif self.selected - self.top < 0:
				self.top = index
			return True
		else:
			return False

	def select_str(self,name):
		"""Select a directory item by string"""
		name = name.lower()
		best_match_count = 0
		best_match_index = -1

		if self.path != '':
			for f in range(len(self.files)):
				match_counter = 0

				file = self.files[f].lower()

				if file == name:
					best_match_index = f
					break;

				for c in range(min(len(file),len(name))):
					if file[c] == name[c]:
						match_counter += 1

				if match_counter > best_match_count:
					best_match_count = match_counter
					best_match_index = f

		if best_match_index != -1:
			self.select_abs(best_match_index)
	
	def selected_is_enterable(self):
		"""Returns true if the selected item can be entered"""
		return True	

	def get_selected_path(self):
		"""Get the currently selected path"""
		return os.path.join(self.path,self.files[self.selected])

	def get_selected(self):
		"""Get a new column object for the item selected in this column"""
		return self.create_column(self.get_selected_path())

# Viewer is a panel that maintains a list of column objects
class Viewer():
	def __init__(self,win,path):
		"""Constructor
		Store curses window used in the viewer, and load the initial path
		"""
		# Store curses window
		self.win = win

		# Initialize column list
		self.num_columns = 0
		self.columns = [] # List of column objects
		self.col_win = [] # List of curses windows for the columns

		# Declare buffer timeout
		self.buffer_time = 0
		self.select_timeout = 1.0

		# Initialize directory path
		dirpath = ""

		# Load directories from root up to the current directory, and construct columns
		for dir_comp in path.split('/'):
			dirpath = dirpath + dir_comp + '/'
			new_dir = Directory(dirpath)
			self.columns.append(new_dir)

		# Set the initial number of columns
		self.set_num_columns(N_MIN_COLUMNS)

	def set_num_columns(self, num_columns):
		"""Set the number of columns"""
		if num_columns >= N_MIN_COLUMNS:
			# Get window size
			[maxy,maxx] = self.win.getmaxyx()

			# Calculate column width, and left margin size
			colsize = int(maxx/num_columns)
			marginsize = maxx % num_columns

			# Only reconstruct the windows if the new column size is at least the min col width
			if colsize >= N_MIN_COL_WIDTH:
				self.num_columns = num_columns
				self.col_wins = []
				for i in range(num_columns):
					new_win = curses.newwin(maxy,colsize, 0, marginsize + i*colsize)# maxx % num_columns)
					self.col_wins.append(new_win)
			
				return True
		return False

	def get_active_column(self):
		"""Get the currently active column or path.
		This is the column in which items can be selected.
		"""
		return self.columns[-2]

	def get_active_path(self):
		"""Get the currently active path"""
		return self.get_active_column().path

	def get_selected_path(self):
		"""Get the currently selected path. This is the rightmost column."""
		return self.columns[-1].path

	def right_col_win(self):
		return min(len(self.col_wins)-1,len(self.columns)-1)
		
	def redraw(self):
		"""Clear and redraw the entire viewer"""
		# Clear the window
		self.win.clear()
		# Blit the buffer
		self.win.noutrefresh()

		# Iterate over all columns, telling each to refresh with a given window
		# Iterate over the viewable columns
		for i in range(len(self.col_wins)):
			i_offset = i-len(self.col_wins) 
			if i_offset >= -len(self.columns):
				self.columns[i_offset].redraw(self.col_wins[i])

	def select_rel(self,offset):
		"""Move selection relative to current selection"""
		if self.columns[-2].select_rel(offset):
			# Load newly selected directory, if available, otherwise, this will
			# return an empty directory object
			self.columns[-1] = self.get_active_column().get_selected()

			# Get rightmost col
			right_col_win = self.right_col_win()

			# Clear the rightmost column
			self.col_wins[right_col_win].clear()
			self.col_wins[right_col_win].noutrefresh()

			return True
		return False
	
	def buffer_select_ch(self,str):
		"""Select an item based on text input"""
		if len(str) == 1:
			curtime = time.time()
			if curtime - self.buffer_time < self.select_timeout:
				if str == '/':
					self.enter()
				# Continue appending to the buffer
				self.select_buffer += str 
			else:
				# Start new buffer
				self.select_buffer = str

			self.buffer_time = curtime
			self.columns[-2].select_str(self.select_buffer)
			self.select_rel(0)

	### Commands from user
	def add_col(self):
		"""Remove a column and redraw"""
		return self.set_num_columns(self.num_columns+1)

	def rem_col(self):
		"""Remove a column and redraw"""
		return self.set_num_columns(self.num_columns-1)
	
	def leave(self):
		"""Leave the active column"""
		logging.debug("n columns %d" % len(self.columns))
		if len(self.columns) > 2:
			# Clear the rightmost column and delete it
			#self.col_wins[-1].clear()
			#self.col_wins[-1].refresh()
			self.columns.pop()

			# Redraw the viewer
			self.redraw()

			# Set the last column to have no selection
			self.columns[-1].selected = -1

			return True
		return False

	def enter(self):
		"""Enter a selected item
		Entering an item in a column will construct a new, empty, column in the
		rightmost slot, pushing the other columns to the left. Only "enterable"
		items can be entered. This is a class of items that can be browsed in a
		hierarchical manner similar to a directory structure. This is decided by the
		column subclass. For example, future support for the browsing of archives or
		other files within the ionian interface could utilize this interface.
		"""
		if self.columns[-1].is_enterable:
			# Add an empty column
			self.columns.append(Column())

			# Clear and refresh the rightmost subwindow
			#self.col_wins[-1].clear()
			#self.col_wins[-1].refresh()

			return True
		return False

	def down(self):
		"""Move selection downward one item"""
		return self.select_rel(+1)

	def up(self):
		"""Move selection upward one item"""
		return self.select_rel(-1)

class Ionian():
	def __init__(self):
		"""Construct and initialize command map"""
		self.win_content = 0
		self.win_status = 0
		self.win_command = 0
		self.viewer = 0

		self.size = [0,0]
		self.size_changed = True

	def run(self,stdscr,key_handler):
		"""Execution loop"""
		# Store stdscr
		self.stdscr = stdscr
		#curses.use_default_colors()
		stdscr.refresh()

		# Define colors
		# Standard file colors
		curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
		curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)

		# Directory colors
		curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)
		curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_WHITE)

		# Capture special keys
		self.stdscr.keypad(1)
		self.stdscr.leaveok(1)
		self.stdscr.nodelay(0)

		# Create the sub-windows
		self.redraw()

		# Create columnms
		self.viewer = Viewer(self.win_content, os.getcwd())

		# Setup keyhandler
		self.key_handler = key_handler

		# Set keep_running
		self.keep_running = True

		# Define command map
		self.cmds = {
			'+': self.viewer.add_col,
			'-': self.viewer.rem_col,
			"KEY_LEFT": self.viewer.leave,
			"KEY_RIGHT": self.viewer.enter,
			"KEY_DOWN":	self.viewer.down,
			"KEY_UP":	self.viewer.up,
			"KEY_RESIZE":	self.redraw,
			"\n":	self.open_file
			}
		self.viewer.redraw()

		# Input handler
		while self.keep_running is True:
			# Get window size and create windows
			self.update_size()

			# Draw the status line
			self.win_status.hline(0,0,' ',self.size[1],curses.A_REVERSE)
			self.win_status.addnstr(0,1,self.viewer.get_active_path(), self.size[1]-2, curses.A_REVERSE) 
			self.win_status.refresh()

			# Block and get character
			needs_update = self.process_char()

			# Redraw if necessaru
			self.viewer.redraw()

			# Draw the columns
			if needs_update:
				curses.doupdate()

			# Sleep for a bit
			time.sleep(0.03)

	def process_char(self):
		"""Block, retrieve and process character"""
		needs_update = False
		serviced_ch = 0 
		try:
			# After first key captured grab and process as much input as possible
			# before having to update the screen
			while True:
				# Block on getting key
				ch = self.stdscr.getkey()
				serviced_ch = serviced_ch + 1
				# Set to non-blocking mode
				self.stdscr.nodelay(1)

				# Process character
				ch = self.key_handler.process_char(ch)
				self.viewer.buffer_select_ch(ch)

				# Call static command
				try:
					needs_update = self.cmds[ch]()
				except:
					logging.debug("Pressed \""+ch+"\"")
		except:
			pass

		logging.debug("Serviced "+str(serviced_ch)+" character(s)")
		# Reset nodelay
		self.stdscr.nodelay(0)
		return needs_update

	def update_size(self):
		"""Check the size of the screen, if it has changed, store the new size"""
		[maxy,maxx] = self.stdscr.getmaxyx()
		if maxy != self.size[0] or maxx != self.size[1]:
			self.size_changed = True
			self.size = [maxy,maxx]

	def redraw(self):
		"""If the screen size changes, this will re-draw all of the windows"""
		# Get window size and create windows
		self.update_size()

		# Only redraw everything if the screen resizes
		if self.size_changed:
			logging.debug("RESIZE")
			self.size_changed = False
			[maxy, maxx] = self.size

			del(self.win_content)
			del(self.win_status)
			del(self.win_command)		

			self.win_content = curses.newwin(maxy-2,maxx,0,0)
			self.win_status = curses.newwin(1,maxx,maxy-2,0)
			self.win_command = curses.newwin(1,maxx,maxy-1,0)

			if self.viewer:
				self.viewer.win = self.win_content
				self.viewer.set_num_columns(self.viewer.num_columns)

			self.stdscr.clear();
			self.stdscr.refresh();

			self.win_status.clear()
			self.win_status.refresh()

			self.win_command.clear()
			self.win_command.refresh()

			return True

		return False

	def error(self,err_str):
		"""Display an error string in the command window"""
		self.win_command.clear()
		self.win_command.addstr(err_str)
		self.win_command.noutrefresh()

	def open_file(self):
		"""Open a file with external editor"""
		os.system("vim \""+self.viewer.get_selected_path()+"\"")
		self.stdscr.keypad(1)


env = Ionian()
curses.wrapper(env.run,VimHandler())

