using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

internal static class Program
{
    private const uint DetachedProcess = 0x00000008;
    private const uint CreateUnicodeEnvironment = 0x00000400;
    private const uint Infinite = 0xFFFFFFFF;
    private const int StandardInputHandle = -10;
    private const int StandardOutputHandle = -11;
    private const int StandardErrorHandle = -12;
    private const int StartFlagUseShowWindow = 0x00000001;
    private const int StartFlagUseStandardHandles = 0x00000100;
    private const short ShowWindowHidden = 0;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct StartupInfo
    {
        public int StructureSize;
        public string Reserved;
        public string Desktop;
        public string Title;
        public int PositionX;
        public int PositionY;
        public int SizeX;
        public int SizeY;
        public int CountCharsX;
        public int CountCharsY;
        public int FillAttribute;
        public int Flags;
        public short ShowWindow;
        public short ReservedSize;
        public IntPtr ReservedPointer;
        public IntPtr StandardInput;
        public IntPtr StandardOutput;
        public IntPtr StandardError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ProcessInformation
    {
        public IntPtr ProcessHandle;
        public IntPtr ThreadHandle;
        public int ProcessId;
        public int ThreadId;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcessW(
        string applicationName,
        StringBuilder commandLine,
        IntPtr processAttributes,
        IntPtr threadAttributes,
        [MarshalAs(UnmanagedType.Bool)] bool inheritHandles,
        uint creationFlags,
        IntPtr environment,
        string currentDirectory,
        ref StartupInfo startupInfo,
        out ProcessInformation processInformation
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr GetStdHandle(int standardHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetExitCodeProcess(IntPtr processHandle, out uint exitCode);

    [DllImport("kernel32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);

    private static int Main(string[] arguments)
    {
        string launcherDirectory = AppDomain.CurrentDomain.BaseDirectory;
        string nodePath = Path.Combine(launcherDirectory, "node-console.exe");
        if (!File.Exists(nodePath))
        {
            return 2;
        }

        StringBuilder commandLine = new StringBuilder(QuoteWindowsArgument(nodePath));
        foreach (string argument in arguments)
        {
            commandLine.Append(' ');
            commandLine.Append(QuoteWindowsArgument(argument));
        }

        StartupInfo startupInfo = new StartupInfo
        {
            StructureSize = Marshal.SizeOf(typeof(StartupInfo)),
            Flags = StartFlagUseShowWindow | StartFlagUseStandardHandles,
            ShowWindow = ShowWindowHidden,
            StandardInput = GetStdHandle(StandardInputHandle),
            StandardOutput = GetStdHandle(StandardOutputHandle),
            StandardError = GetStdHandle(StandardErrorHandle),
        };

        ProcessInformation processInformation;
        bool processStarted = CreateProcessW(
            nodePath,
            commandLine,
            IntPtr.Zero,
            IntPtr.Zero,
            true,
            DetachedProcess | CreateUnicodeEnvironment,
            IntPtr.Zero,
            Environment.CurrentDirectory,
            ref startupInfo,
            out processInformation
        );

        if (!processStarted)
        {
            return new Win32Exception(Marshal.GetLastWin32Error()).NativeErrorCode;
        }

        try
        {
            CloseHandle(processInformation.ThreadHandle);
            WaitForSingleObject(processInformation.ProcessHandle, Infinite);

            uint exitCode;
            if (!GetExitCodeProcess(processInformation.ProcessHandle, out exitCode))
            {
                return new Win32Exception(Marshal.GetLastWin32Error()).NativeErrorCode;
            }

            return unchecked((int)exitCode);
        }
        finally
        {
            CloseHandle(processInformation.ProcessHandle);
        }
    }

    private static string QuoteWindowsArgument(string argument)
    {
        if (argument.Length > 0 && argument.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
        {
            return argument;
        }

        StringBuilder quoted = new StringBuilder();
        quoted.Append('"');
        int backslashCount = 0;

        foreach (char character in argument)
        {
            if (character == '\\')
            {
                backslashCount += 1;
                continue;
            }

            if (character == '"')
            {
                quoted.Append('\\', (backslashCount * 2) + 1);
                quoted.Append('"');
                backslashCount = 0;
                continue;
            }

            quoted.Append('\\', backslashCount);
            quoted.Append(character);
            backslashCount = 0;
        }

        quoted.Append('\\', backslashCount * 2);
        quoted.Append('"');
        return quoted.ToString();
    }
}
