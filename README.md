# Earwig
## The crawling bug that crawls bugs
Usage:

```
usage: earwig [-h] [-f FROM_TIME] [-t TO_TIME] [-i INTERVAL] [-o OUTPUT]
              [-j THREADS] [-H] [-q] [-v]
              bundle_id

Download Google Play ANR reports

positional arguments:
  bundle_id             the bundle id to download reports for

optional arguments:
  -h, --help            show this help message and exit
  -f FROM_TIME, --from FROM_TIME
                        specify download start time (defaults to the previous
                        hour)
  -t TO_TIME, --to TO_TIME
                        specify download end time
  -i INTERVAL, --interval INTERVAL
                        specify time period to download, in seconds (defaults
                        to 1 hour)
  -o OUTPUT, --output OUTPUT
                        specify the output filename (defaults to
                        output/YYYYMMDD/HH.json.gz)
  -j THREADS, --threads THREADS
                        set the parallelism (default: 1)
  -H, --headless        run in headless mode, i.e. do not use Selenium and
                        expect a valid state file to be present
  -q, --quiet           minimize execution output
  -v, --verbose         report more information during execution
```

