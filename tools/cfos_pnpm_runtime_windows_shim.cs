using System;
using System.Diagnostics;
using System.IO;
using System.Text;

internal static class CfosPnpmRuntimeWindowsShim
{
    private const int RejectedCommand = 64;

    private static string QuoteWindowsArgument(string value)
    {
        if (value.Length > 0 && value.IndexOfAny(new[] { ' ', '\t', '\n', '\v', '"' }) < 0)
        {
            return value;
        }

        var result = new StringBuilder();
        result.Append('"');
        var backslashes = 0;
        foreach (var character in value)
        {
            if (character == '\\')
            {
                backslashes++;
                continue;
            }

            if (character == '"')
            {
                result.Append('\\', backslashes * 2 + 1);
                result.Append('"');
                backslashes = 0;
                continue;
            }

            result.Append('\\', backslashes);
            backslashes = 0;
            result.Append(character);
        }

        result.Append('\\', backslashes * 2);
        result.Append('"');
        return result.ToString();
    }

    private static bool IsExactViteBuild(string[] args)
    {
        if (args.Length != 5 && args.Length != 6) return false;
        if (args[0] != "exec" || args[1] != "vite" || args[2] != "build" ||
            args[3] != "-c" || args[4] != "vite.config.ts") return false;
        return args.Length == 5 || args[5] == "--watch";
    }

    private static bool IsLocalWranglerDev(string[] args)
    {
        if (args.Length < 3 || args[0] != "exec" || args[1] != "wrangler" || args[2] != "dev")
        {
            return false;
        }

        foreach (var argument in args)
        {
            if (argument.Equals("--remote", StringComparison.OrdinalIgnoreCase) ||
                argument.StartsWith("--remote=", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }
        }
        return true;
    }

    private static bool IsExactCapnwebBuild(string[] args)
    {
        return args.Length == 5 && args[0] == "exec" && args[1] == "capnweb-validate" &&
            args[2] == "build" && args[3] == "--out" && args[4] == ".wrangler/validate";
    }

    private static bool IsExactWorkshopBuildWorker(string[] args)
    {
        return args.Length == 2 && args[0] == "run" && args[1] == "build:worker";
    }

    private static int RunNode(string nodeExecutable, string cli, string[] args, int firstArgument)
    {
        var command = new StringBuilder(QuoteWindowsArgument(cli));
        for (var index = firstArgument; index < args.Length; index++)
        {
            command.Append(' ');
            command.Append(QuoteWindowsArgument(args[index]));
        }

        using (var process = new Process())
        {
            process.StartInfo = new ProcessStartInfo
            {
                FileName = nodeExecutable,
                Arguments = command.ToString(),
                WorkingDirectory = Environment.CurrentDirectory,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            process.OutputDataReceived += (_, eventArgs) =>
            {
                if (eventArgs.Data != null) Console.Out.WriteLine(eventArgs.Data);
            };
            process.ErrorDataReceived += (_, eventArgs) =>
            {
                if (eventArgs.Data != null) Console.Error.WriteLine(eventArgs.Data);
            };
            process.Start();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            process.WaitForExit();
            process.WaitForExit();
            return process.ExitCode;
        }
    }

    public static int Main(string[] args)
    {
        var nodeExecutable = Environment.GetEnvironmentVariable("CFOS_EXACT_NODE_EXE");
        var evaluationRoot = Environment.GetEnvironmentVariable("CFOS_EVALUATION_ROOT");
        if (string.IsNullOrWhiteSpace(nodeExecutable) ||
            string.IsNullOrWhiteSpace(evaluationRoot) ||
            !Path.IsPathRooted(nodeExecutable) ||
            !Path.IsPathRooted(evaluationRoot) ||
            !File.Exists(nodeExecutable))
        {
            Console.Error.WriteLine("CFOS runtime shim is missing its exact Node/evaluation-root binding.");
            return RejectedCommand;
        }

        var root = Path.GetFullPath(evaluationRoot).TrimEnd(Path.DirectorySeparatorChar) +
            Path.DirectorySeparatorChar;
        var workingDirectory = Path.GetFullPath(Environment.CurrentDirectory);
        if (!workingDirectory.StartsWith(root, StringComparison.OrdinalIgnoreCase))
        {
            Console.Error.WriteLine("CFOS runtime shim rejected a working directory outside the evaluation root.");
            return RejectedCommand;
        }

        string cli;
        int firstArgument;
        if (IsExactViteBuild(args))
        {
            cli = Path.Combine(workingDirectory, "node_modules", "vite", "bin", "vite.js");
            firstArgument = 2;
        }
        else if (IsLocalWranglerDev(args))
        {
            cli = Path.Combine(workingDirectory, "node_modules", "wrangler", "bin", "wrangler.js");
            firstArgument = 2;
        }
        else if (IsExactCapnwebBuild(args))
        {
            cli = Path.Combine(
                workingDirectory, "node_modules", "capnweb-validate", "dist", "cli.cjs");
            firstArgument = 2;
        }
        else if (IsExactWorkshopBuildWorker(args))
        {
            var browserRuntime = Path.Combine(workingDirectory, "build-browser-runtime.mjs");
            var capnweb = Path.Combine(
                workingDirectory, "node_modules", "capnweb-validate", "dist", "cli.cjs");
            if (!File.Exists(browserRuntime) || !File.Exists(capnweb))
            {
                Console.Error.WriteLine("CFOS runtime shim could not resolve Workshop build inputs.");
                return RejectedCommand;
            }

            var browserStatus = RunNode(
                nodeExecutable, browserRuntime, new string[0], 0);
            if (browserStatus != 0) return browserStatus;
            return RunNode(
                nodeExecutable,
                capnweb,
                new[] { "build", "--out", ".wrangler/validate" },
                0);
        }
        else
        {
            Console.Error.WriteLine(
                "CFOS runtime shim rejected a command outside the local runtime allowlist.");
            return RejectedCommand;
        }

        if (!File.Exists(cli))
        {
            Console.Error.WriteLine("CFOS runtime shim could not resolve the lock-installed CLI.");
            return RejectedCommand;
        }
        return RunNode(nodeExecutable, cli, args, firstArgument);
    }
}
