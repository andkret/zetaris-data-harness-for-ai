# Connect Tableau to Zetaris Cloud

Tableau Desktop connects to Zetaris over JDBC, with the Zetaris JDBC driver. The connection is encrypted, so the driver needs three extra settings in a small properties file. You set this up once.

> Tested with Tableau Desktop on macOS (Apple silicon) and Zetaris Cloud Hobby. Windows works the same way, only the folders differ.

## What you need

- **Tableau Desktop** (the free trial works)
- The **Zetaris JDBC driver** (`.jar` file): https://kbase.zetaris.com/hubfs/ndp-jdbc-driver-2.1.0.13-driver.jar
- Your Zetaris **cluster hostname** and login

## 1. Install the driver

Copy the Zetaris driver `.jar` into Tableau's driver folder, and restart Tableau if it's open:

| System | Folder |
|---|---|
| macOS | `~/Library/Tableau/Drivers/` |
| Windows | `C:\Program Files\Tableau\Drivers\` |

Create the folder if it doesn't exist.

## 2. Get a truststore

Zetaris Cloud only accepts encrypted connections. Its certificate is issued by a public certificate authority (Amazon), so any standard Java truststore trusts it. But the Zetaris driver doesn't fall back to a default: you have to point it to a truststore file explicitly.

The easiest source is the Java runtime that ships with Tableau. Find its `cacerts` file and copy it to your home folder:

**macOS:**

```bash
find /Applications/Tableau*.app -name cacerts 2>/dev/null
cp "<path from the line above>" ~/zetaris-cacerts
```

**Windows (PowerShell):**

```powershell
Get-ChildItem "C:\Program Files\Tableau" -Recurse -Filter cacerts -ErrorAction SilentlyContinue
Copy-Item "<path from the line above>" "$HOME\zetaris-cacerts"
```

The default password of this file is `changeit`.

> Any other Java `cacerts` file works too, for example from a JDK you already have installed.

## 3. Create the properties file

Create a text file called `zetaris.properties` in your home folder with these three lines. Replace the path with the full path to your truststore:

```properties
ssl=true
sslTrustStore=/Users/<your-user>/zetaris-cacerts
trustStorePassword=changeit
```

On Windows, use forward slashes in the path, for example `sslTrustStore=C:/Users/<your-user>/zetaris-cacerts`.

- `ssl=true` turns on the encrypted connection.
- `sslTrustStore` and `trustStorePassword` tell the driver which certificates to trust.

## 4. Connect

1. In Tableau, under **Connect → To a Server → More…**, choose **Other Databases (JDBC)**.
2. **URL:** `jdbc:zetaris:lightning@jdbc.<cluster-hostname>:10000`

   That's your cluster's hostname with `jdbc.` in front. Example: if you log in at `new-ui.1234abcd-….cloud.zetaris.com`, the URL is `jdbc:zetaris:lightning@jdbc.1234abcd-….cloud.zetaris.com:10000`. You also find it in the Zetaris UI under **Cloud Gateway manager**.
3. **Dialect:** SQL92
4. **Username / Password:** your Zetaris login
5. **Properties file:** select your `zetaris.properties`
6. Click **Sign In**.

Under **Schema**, you now see your Zetaris data sources and data marts.

## What Tableau can see

- **Data sources** and **data marts** show up as schemas, their tables as tables.
- **The Unified Semantic Layer doesn't show up directly.** To use it in Tableau, publish what you need as a view on the semantic layer and add the view to a data mart (see lesson 3.6).
- **Custom SQL doesn't work** with Tableau's generic JDBC connector. Build what you need as a view in Zetaris instead.

## Troubleshooting

| Error | Fix |
|---|---|
| `UnknownHostException` | The hostname needs the `jdbc.` prefix: `jdbc.<cluster-hostname>`, not `new-ui.…` or the bare cluster hostname. |
| `Invalid status 21` | The connection isn't encrypted. Check that `ssl=true` is in the properties file, and that the properties file is selected in the connection dialog. |
| `sslTrustStore is not set` | The properties file is missing the truststore lines, or the path is wrong. Use the full path, not `~`. |
| Errors with other dialects (e.g. PostgreSQL) | Use **SQL92**. |
| A data mart shows no tables | Open the mart in Zetaris and check that it was saved. The **Save** button only appears after you've added a table. |
| New columns in a view don't show up | Refresh the data source in Tableau. |