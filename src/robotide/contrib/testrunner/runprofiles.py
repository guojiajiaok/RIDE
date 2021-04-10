# Copyright 2010 Orbitz WorldWide
#
# Ammended by Helio Guilherme <helioxentric@gmail.com>
# Copyright 2011-2015 Nokia Networks
# Copyright 2016-     Robot Framework Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""runProfiles.py

This module contains profiles for running robot tests via the
runnerPlugin.

Each class that is a subclass as BaseProfile will appear in a
drop-down list within the plugin. The chosen profile will be used to
build up a command that will be passed in the tests to run as well as
any additional arguments.
"""

import os
import time
import wx

from robotide import pluginapi
from robotide.context import IS_WINDOWS
from robotide.contrib.testrunner.usages import USAGE
from robotide.lib.robot.utils import format_time
from robotide.robotapi import DataError, Information
from robotide.utils import overrides, ArgumentParser
from robotide.widgets import ButtonWithHandler, Label, RIDEDialog
from sys import getfilesystemencoding
from wx.lib.filebrowsebutton import FileBrowseButton

OUTPUT_ENCODING = getfilesystemencoding()


class BaseProfile(object):
    """Base class for all test runner profiles

    At a minimum each profile must set the name attribute, which is
    how the profile will appear in the dropdown list.

    In case some settings are needed, provide default_settings class attribute
    with default values.

    This class (BaseProfile) will _not_ appear as one of the choices.
    Think of it as an abstract class, if Python 2.5 had such a thing.
    """

    # this will be set to the plugin instance at runtime
    plugin = None
    default_settings = {}

    def __init__(self, plugin):
        """plugin is required so that the profiles can save their settings"""
        self.plugin = plugin
        self._panel = None

    def get_toolbar(self, parent):
        """Returns a panel with toolbar controls for this profile"""
        if self._panel is None:
            self._panel = wx.Panel(parent, wx.ID_ANY)
        return self.panel

    def enable_toolbar(self):
        if self._panel is None:
            return
        self._panel.Enable()

    def disable_toolbar(self):
        if self._panel is None:
            return
        self._panel.Enable(False)

    def delete_pressed(self):
        """Handle delete key pressing"""
        pass

    def get_command(self):
        """Returns a command for this profile"""
        return 'robot'

    def get_command_args(self):
        """Return a list of command arguments unique to this profile.

        Returned arguments are in format accepted by Robot Framework's argument
        file.
        """
        return []

    def get_settings(self):
        """Return a list of settings unique to this profile.

        Returned settings can be used when running tests.
        """
        return []

    def set_setting(self, name, value):
        """Sets a plugin setting

        setting is automatically prefixed with profile's name and it can be
        accessed with direct attribute access. See also __getattr__.
        """
        self.plugin.save_setting(self._get_setting_name(name), value, delay=2)

    def format_error(self, error, returncode):
        return error, self._create_error_log_message(error, returncode)

    def _create_error_log_message(self, error, returncode):
        return None

    def __getattr__(self, name):
        """Provides attribute access to profile's settings

        If for example default_settings = {'setting1' = ""} is defined
        then setting1 value can be used like self.setting1
        set_setting is used to store the value.
        """
        try:
            return getattr(self.plugin, self._get_setting_name(name))
        except AttributeError:
            try:
                return getattr(self.plugin, name)
            except AttributeError:
                if name in self.default_settings:
                    return self.default_settings[name]
                raise

    def _get_setting_name(self, name):
        """Adds profile's name to the setting."""
        return "%s_%s" % (self.name.replace(' ', '_'), name)


RF_INSTALLATION_NOT_FOUND = """Robot Framework installation not found.<br>
To run tests, you need to install Robot Framework separately.<br>
See <a href="http://robotframework.org">http://robotframework.org</a> for
installation instructions.
"""


class PybotProfile(BaseProfile, RIDEDialog):
    """A runner profile which uses robot

    It is assumed that robot is on the path
    """
    name = "robot"
    default_settings = {"arguments": "",
                        "output_directory": "",
                        "include_tags": "",
                        "exclude_tags": "",
                        "are_log_names_with_suite_name": False,
                        "are_log_names_with_timestamp": False,
                        "are_saving_logs": False,
                        "apply_include_tags": False,
                        "apply_exclude_tags": False}

    def __init__(self, plugin):
        BaseProfile.__init__(self, plugin)
        self._defined_arguments = self.arguments
        self._toolbar = None

    def get_toolbar(self, parent):
        if self._toolbar is None:
            self._toolbar = wx.Panel(parent, wx.ID_ANY)
            self._mysettings = RIDEDialog(parent=self._toolbar)
            self._toolbar.SetBackgroundColour(self._mysettings.color_background)
            self._toolbar.SetForegroundColour(self._mysettings.color_foreground)
            sizer = wx.BoxSizer(wx.VERTICAL)
            for item in self.get_toolbar_items(self._toolbar):
                sizer.Add(item, 0, wx.EXPAND)
            self._toolbar.SetSizer(sizer)
        return self._toolbar

    def get_toolbar_items(self, parent):
        return [self._get_arguments_panel(parent),
                self._get_tags_panel(parent),
                self._get_log_options_panel(parent)]

    def enable_toolbar(self):
        if self._toolbar is None:
            return
        self._enable_toolbar()

    def disable_toolbar(self):
        if self._toolbar is None:
            return
        self._enable_toolbar(False)

    def _enable_toolbar(self, enable=True):
        for panel in self._toolbar.GetChildren():
            if isinstance(panel, wx.CollapsiblePane):
                panel = panel.GetPane()
            panel.Enable(enable)

    @overrides(BaseProfile)
    def delete_pressed(self):
        focused = wx.Window.FindFocus()
        if focused not in [self._arguments, self._include_tags,
                           self._exclude_tags]:
            return
        start, end = focused.GetSelection()
        focused.Remove(start, max(end, start + 1))

    def get_command(self):
        from subprocess import call
        from tempfile import TemporaryFile
        try:
            with TemporaryFile(mode="at") as out:
                result = call(["robot", "--version"], stdout=out)
            if result == 251:
                return "robot"

            with TemporaryFile(mode="at") as out:
                result = call(["robot.bat" if os.name == "nt" else "robot",
                               "--version"], stdout=out)
            if result == 251:
                return "robot.bat" if os.name == "nt" else "robot"
        except OSError:
            try:
                with TemporaryFile(mode="at") as out:
                    result = call(["pybot.bat" if os.name == "nt" else "pybot",
                                   "--version"], stdout=out)
                if result == 251:
                    return "pybot.bat" if os.name == "nt" else "pybot"
            except OSError:
                result = "no pybot"
        return result

    def get_command_args(self):
        args = self._get_arguments()
        if self.output_directory and \
                '--outputdir' not in args and \
                '-d' not in args:
            args.extend(['-d', os.path.abspath(self.output_directory)])

        log_name_format = '%s'
        if self.are_log_names_with_suite_name:
            log_name_format = f'{self.plugin.model.suite.name}-%s'
            if '--log' not in args and '-l' not in args:
                args.extend(['-l', log_name_format % 'Log.html'])
            if '--report' not in args and '-r' not in args:
                args.extend(['-r', log_name_format % 'Report.html'])
            if '--output' not in args and '-o' not in args:
                args.extend(['-o', log_name_format % 'Output.xml'])

        if self.are_saving_logs and \
                '--debugfile' not in args and \
                '-b' not in args:
            args.extend(['-b', log_name_format % 'Message.log'])

        if self.are_log_names_with_timestamp and \
                '--timestampoutputs' not in args and \
                '-T' not in args:
            args.append('-T')

        if self.apply_include_tags and self.include_tags:
            for include in self._get_tags_from_string(self.include_tags):
                args.append('--include=%s' % include)

        if self.apply_exclude_tags and self.exclude_tags:
            for exclude in self._get_tags_from_string(self.exclude_tags):
                args.append('--exclude=%s' % exclude)
        return args

    def _get_arguments(self):
        if IS_WINDOWS:
            self._parse_windows_command()
        return self._defined_arguments.split()

    def _parse_windows_command(self):
        from subprocess import Popen, PIPE
        try:
            p = Popen(['echo', self.arguments], stdin=PIPE, stdout=PIPE,
                      stderr=PIPE, shell=True)
            output, _ = p.communicate()
            output = str(output).lstrip("b\'").strip()
            self._defined_arguments = output.replace('"', '').replace('\'', '')\
                .replace('\\\\', '\\').replace('\\r\\n', '')
        except IOError as e:
            # print("DEBUG: parser_win_comm IOError: %s" % e)
            pass

    @staticmethod
    def _get_tags_from_string(tag_string):
        tags = []
        for tag in tag_string.split(","):
            tag = tag.strip().replace(' ', '')
            if len(tag) > 0:
                tags.append(tag)
        return tags

    def get_settings(self):
        settings = []
        if self.are_saving_logs:
            name = 'Console.txt'
            if self.are_log_names_with_timestamp:
                start_timestamp = format_time(time.time(), '', '-', '')
                base, ext = os.path.splitext(name)
                base = f'{base}-{start_timestamp}'
                name = base + ext

            if self.are_log_names_with_suite_name:
                name = f'{self.plugin.model.suite.name}-{name}'
            settings.extend(['console_log_name', name])
        return settings

    def _create_error_log_message(self, error, returncode):
        # bash and zsh use return code 127 and the text `command not found`
        # In Windows, the error is `The system cannot file the file specified`
        if b'not found' in error \
                or returncode == 127 or \
                b'system cannot find the file specified' in error:
            return pluginapi.RideLogMessage(
                RF_INSTALLATION_NOT_FOUND, notify_user=True)
        return None

    def _get_log_options_panel(self, parent):
        collapsible_pane = wx.CollapsiblePane(
            parent, wx.ID_ANY, '日志选项',
            style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE)
        collapsible_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,
                              self.OnCollapsiblePaneChanged,
                              collapsible_pane)
        pane = collapsible_pane.GetPane()
        pane.SetBackgroundColour(self._mysettings.color_background)
        pane.SetForegroundColour(self._mysettings.color_foreground)
        label = Label(pane, label="输出目录: ")
        self._output_directory_text_ctrl = \
            self._create_text_ctrl(pane, self.output_directory,
                                   "removed due unicode_error (delete this)",
                                   self.OnOutputDirectoryChanged)
        self._output_directory_text_ctrl.SetBackgroundColour(self._mysettings.color_secondary_background)
        self._output_directory_text_ctrl.SetForegroundColour(self._mysettings.color_secondary_foreground)
        button = ButtonWithHandler(pane, "...", self._handle_select_directory)
        button.SetBackgroundColour(self._mysettings.color_secondary_background)
        button.SetForegroundColour(self._mysettings.color_secondary_foreground)
        horizontal_sizer = wx.BoxSizer(wx.HORIZONTAL)
        horizontal_sizer.Add(label, 0,
                             wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        horizontal_sizer.Add(self._output_directory_text_ctrl, 1, wx.EXPAND)
        horizontal_sizer.Add(button, 0, wx.LEFT | wx.RIGHT, 10)

        suite_name_outputs_cb = self._create_checkbox(
            pane, self.are_log_names_with_suite_name,
            "添加集合名到日志名", self.OnSuiteNameOutputsCheckBox)
        timestamp_outputs_cb = self._create_checkbox(
            pane, self.are_log_names_with_timestamp,
            "添加时间戳到日志名", self.OnTimestampOutputsCheckbox)
        save_logs_cb = self._create_checkbox(
            pane, self.are_saving_logs,
            "保存控制台与消息到日志", self.OnSaveLogsCheckbox)

        vertical_sizer = wx.BoxSizer(wx.VERTICAL)
        vertical_sizer.Add(horizontal_sizer, 0, wx.EXPAND)
        vertical_sizer.Add(suite_name_outputs_cb, 0, wx.LEFT | wx.TOP, 10)
        vertical_sizer.Add(timestamp_outputs_cb, 0, wx.LEFT | wx.TOP, 10)
        vertical_sizer.Add(save_logs_cb, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 10)
        pane.SetSizer(vertical_sizer)
        return collapsible_pane

    def OnOutputDirectoryChanged(self, evt):
        value = self._output_directory_text_ctrl.GetValue()
        self.set_setting("output_directory", value)

    def _handle_select_directory(self, event):
        path = self._output_directory_text_ctrl.GetValue()
        dlg = wx.DirDialog(None, "Select Logs Directory",
                           path, wx.DD_DEFAULT_STYLE)
        dlg.SetBackgroundColour(self._mysettings.color_background)
        dlg.SetForegroundColour(self._mysettings.color_foreground)
        for item in dlg.GetChildren():  # DEBUG This is not working
            item.SetBackgroundColour(self._mysettings.color_secondary_background)
            item.SetForegroundColour(self._mysettings.color_secondary_foreground)
        if dlg.ShowModal() == wx.ID_OK and dlg.Path:
            self._output_directory_text_ctrl.SetValue(dlg.Path)
        dlg.Destroy()

    def OnSuiteNameOutputsCheckBox(self, evt):
        self.set_setting("are_log_names_with_suite_name", evt.IsChecked())

    def OnTimestampOutputsCheckbox(self, evt):
        self.set_setting("are_log_names_with_timestamp", evt.IsChecked())

    def OnSaveLogsCheckbox(self, evt):
        self.set_setting("are_saving_logs", evt.IsChecked())

    def _get_arguments_panel(self, parent):
        collapsible_pane = wx.CollapsiblePane(
            parent, wx.ID_ANY, '参数',
            style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE)
        collapsible_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,
                              self.OnCollapsiblePaneChanged,
                              collapsible_pane)
        pane = collapsible_pane.GetPane()
        pane.SetBackgroundColour(self._mysettings.color_background)
        pane.SetForegroundColour(self._mysettings.color_foreground)
        self._args_text_ctrl = \
            self._create_text_ctrl(pane, self.arguments,
                                   "removed due unicode_error (delete this)",
                                   self.OnArgumentsChanged)
        self._args_text_ctrl.SetToolTip("Arguments for the test run. "
                                        "Arguments are space separated list.")
        self._args_text_ctrl.SetBackgroundColour(self._mysettings.color_secondary_background)
        self._args_text_ctrl.SetForegroundColour(self._mysettings.color_secondary_foreground)
        horizontal_sizer = wx.BoxSizer(wx.HORIZONTAL)
        horizontal_sizer.Add(self._args_text_ctrl, 1,
                             wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        pane.SetSizer(horizontal_sizer)
        self._validate_arguments(self.arguments or u'')
        return collapsible_pane

    def OnArgumentsChanged(self, evt):
        args = self._args_text_ctrl.GetValue()
        self._validate_arguments(args or u'')
        self.set_setting("arguments", args)
        self._defined_arguments = args

    def _validate_arguments(self, args):
        invalid_message = self._get_invalid_message(args)
        self._args_text_ctrl.SetBackgroundColour(
            'red' if invalid_message else self._mysettings.color_secondary_background)
        self._args_text_ctrl.SetForegroundColour(
            'white' if invalid_message else self._mysettings.color_secondary_foreground)
        if not bool(invalid_message):
            invalid_message = "Arguments for the test run. " \
                              "Arguments are space separated list."
        self._args_text_ctrl.SetToolTip(invalid_message)

    @staticmethod
    def _get_invalid_message(args):
        if not args:
            return None
        try:
            clean_args = args.split("`")  # Shell commands
            for idx, item in enumerate(clean_args):
                clean_args[idx] = item.strip()
                if clean_args[idx][0] != '-':  # Not option, then is argument
                    clean_args[idx] = 'arg'
            args = " ".join(clean_args)
            _, invalid = ArgumentParser(USAGE).parse_args(args.split())
        except Information:
            return 'Does not execute - help or version option given'
        except Exception as e:
            raise DataError(e.message)
        if bool(invalid):
            return f'Unknown option(s): {invalid}'
        return None

    def _get_tags_panel(self, parent):
        """Create a panel to input include/exclude tags"""
        collapsible_pane = wx.CollapsiblePane(
            parent, wx.ID_ANY, '过滤器',
            style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE)
        collapsible_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,
                              self.OnCollapsiblePaneChanged,
                              collapsible_pane)
        pane = collapsible_pane.GetPane()
        pane.SetBackgroundColour(self._mysettings.color_background)
        pane.SetForegroundColour(self._mysettings.color_foreground)
        include_cb = self._create_checkbox(pane, self.apply_include_tags,
                                           "仅这些标签运行:",
                                           self.OnIncludeCheckbox)
        exclude_cb = self._create_checkbox(pane, self.apply_exclude_tags,
                                           "跳过这些标签运行:",
                                           self.OnExcludeCheckbox)
        self._include_tags_text_ctrl = \
            self._create_text_ctrl(pane, self.include_tags, "unicode_error",
                                   self.OnIncludeTagsChanged,
                                   self.apply_include_tags)
        self._exclude_tags_text_ctrl = \
            self._create_text_ctrl(pane, self.exclude_tags, "unicode error",
                                   self.OnExcludeTagsChanged,
                                   self.apply_exclude_tags)
        self._include_tags_text_ctrl.SetBackgroundColour(self._mysettings.color_secondary_background)
        self._include_tags_text_ctrl.SetForegroundColour(self._mysettings.color_secondary_foreground)
        self._exclude_tags_text_ctrl.SetBackgroundColour(self._mysettings.color_secondary_background)
        self._exclude_tags_text_ctrl.SetForegroundColour(self._mysettings.color_secondary_foreground)
        horizontal_sizer = wx.BoxSizer(wx.HORIZONTAL)
        horizontal_sizer.Add(include_cb, 0, wx.ALIGN_CENTER_VERTICAL)
        horizontal_sizer.Add(self._include_tags_text_ctrl, 1, wx.EXPAND)
        horizontal_sizer.Add(exclude_cb, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        horizontal_sizer.Add(self._exclude_tags_text_ctrl, 1, wx.EXPAND)
        # Set Left, Right and Bottom content margins
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(horizontal_sizer, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        pane.SetSizer(sizer)

        return collapsible_pane

    def OnCollapsiblePaneChanged(self, evt=None):
        parent = self._toolbar.GetParent().GetParent()
        parent.Layout()

    def OnIncludeCheckbox(self, evt):
        self.set_setting("apply_include_tags", evt.IsChecked())
        self._include_tags_text_ctrl.Enable(evt.IsChecked())

    def OnExcludeCheckbox(self, evt):
        self.set_setting("apply_exclude_tags", evt.IsChecked())
        self._exclude_tags_text_ctrl.Enable(evt.IsChecked())

    def OnIncludeTagsChanged(self, evt):
        self.set_setting("include_tags", self._include_tags_text_ctrl.GetValue())

    def OnExcludeTagsChanged(self, evt):
        self.set_setting("exclude_tags", self._exclude_tags_text_ctrl.GetValue())

    @staticmethod
    def _create_checkbox(parent, value, title, handler):
        checkbox = wx.CheckBox(parent, wx.ID_ANY, title)
        checkbox.SetValue(value)
        parent.Bind(wx.EVT_CHECKBOX, handler, checkbox)
        return checkbox

    @staticmethod
    def _create_text_ctrl(parent, value, value_for_error,
                          text_change_handler, enable=True):
        try:
            text_ctrl = wx.TextCtrl(parent, wx.ID_ANY, value=value)
        except UnicodeError:
            text_ctrl = wx.TextCtrl(parent, wx.ID_ANY, value=value_for_error)
        text_ctrl.Bind(wx.EVT_TEXT, text_change_handler)
        text_ctrl.Enable(enable)
        return text_ctrl


class CustomScriptProfile(PybotProfile):
    """A runner profile which uses script given by the user"""

    name = "custom script"
    default_settings = dict(PybotProfile.default_settings, runner_script="")

    def get_command(self):
        # strip the starting and ending spaces to ensure
        # /bin/sh finding the executable file
        return self.runner_script.strip()

    def get_cwd(self):
        return os.path.dirname(self.runner_script)

    @overrides(PybotProfile)
    def get_toolbar_items(self, parent):
        return [self._get_run_script_panel(parent),
                self._get_arguments_panel(parent),
                self._get_tags_panel(parent),
                self._get_log_options_panel(parent)]

    def _validate_arguments(self, args):
        # Can't say anything about custom script argument validity
        pass

    def _create_error_log_message(self, error, returncode):
        return None

    def _get_run_script_panel(self, parent):
        panel = wx.Panel(parent, wx.ID_ANY)
        self._script_ctrl = FileBrowseButton(
            panel, labelText="Script to run tests:", size=(-1, -1),
            fileMask="*", changeCallback=self.OnCustomScriptChanged)
        self._script_ctrl.SetValue(self.runner_script)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._script_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        panel.SetSizerAndFit(sizer)
        return panel

    def OnCustomScriptChanged(self, evt):
        self.set_setting("runner_script", self._script_ctrl.GetValue())
