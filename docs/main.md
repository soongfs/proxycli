# CLI Design

The entry point is `proxycli.main:cli`, exposed as the `proxycli` console
script.

## Global Options

```text
proxycli --config/-c PATH --verbose/-v COMMAND
```

- `--config/-c` selects the sing-box config path and defaults to
  `~/.config/proxycli/config.json`.
- `--verbose/-v` enables debug logging.

## Command Tree

```text
proxycli sub update [URL]
proxycli sub show

proxycli node list
proxycli node use TAG

proxycli daemon start
proxycli daemon stop
proxycli daemon restart
proxycli daemon status
proxycli daemon logs --lines/-n 100

proxycli config generate INPUT_FILE
proxycli config show
```

## Argument Specifications

- `sub update [URL]`: URL is optional after the first successful update because
  the saved URL is read from `state.json`.
- `node use TAG`: calls `sing-box selector set proxy <tag>`.
- `config generate INPUT_FILE`: parses local subscription content and writes the
  selected config path.

## Output Formatting

Rich tables are used for state and node listing. JSON output is printed with
Rich's JSON renderer. Mutating commands print a concise success line.

## Shell Completion

Click supports generated shell completion scripts. Example for zsh:

```bash
_PROXYCLI_COMPLETE=zsh_source proxycli > ~/.zfunc/_proxycli
```

Then ensure `~/.zfunc` is in `fpath` and initialize completion in the shell
startup file.
