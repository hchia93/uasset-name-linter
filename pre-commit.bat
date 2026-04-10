@echo off
rem SVN server-side pre-commit hook entry.
rem Place (or symlink) this in <repo>/hooks/pre-commit.bat on the SVN server.
rem
rem Args provided by SVN:
rem   %1 = REPOS path
rem   %2 = TXN id
rem
rem Exit non-zero to reject the commit.

setlocal

set REPOS=%1
set TXN=%2

rem Adjust to match the SVN server environment.
set PYTHON=python
set HOOK=%~dp0src\vcs-hook.py

"%PYTHON%" "%HOOK%" --svn-txn "%REPOS%" "%TXN%" 1>&2
exit /b %ERRORLEVEL%
