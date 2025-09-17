import java.awt.Desktop;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.Base64;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

/**
 * Självständig Spotify-koppling för Java desktop-spel.
 * - OAuth 2.0 PKCE login via lokal callback-server (http://localhost:8888/callback)
 * - Start/paus/next/prev/transfer/list devices
 *
 * Krav:
 * - Java 11+ (HttpClient)
 * - Registrera redirect URI i Spotify Developer Dashboard: http://localhost:8888/callback
 *
 * Snabbstart:
 *   SpotifyConnector sp = new SpotifyConnector("<CLIENT_ID>", "http://localhost:8888/callback");
 *   sp.login(); // öppnar webbläsaren, slutför inloggning
 *   sp.playUri("spotify:track:<TRACK_ID>", null); // spelar på aktiv enhet
 *
 * I spelknapp:
 *   button.addActionListener(e -> {
 *     try { sp.playUri("spotify:track:<TRACK_ID>", null); } catch (Exception ex) { ex.printStackTrace(); }
 *   });
 */
public class SpotifyConnector {

    // ======= Konfiguration =======
    private static final String AUTH_URL  = "https://accounts.spotify.com/authorize";
    private static final String TOKEN_URL = "https://accounts.spotify.com/api/token";
    private static final String API       = "https://api.spotify.com/v1";

    // Begärda scopes – räcker för styrning av uppspelning och läsning av devicelista
    private static final String SCOPES = String.join(" ",
            "user-modify-playback-state",
            "user-read-playback-state"
    );

    // ======= Instansfält =======
    private final String clientId;
    private final String redirectUri;
    private final HttpClient http;

    // OAuth/Token
    private String codeVerifier;
    private String accessToken;
    private String refreshToken;
    private Instant accessTokenExpiry = Instant.EPOCH; // när accessToken går ut

    public SpotifyConnector(String clientId, String redirectUri) {
        this.clientId = Objects.requireNonNull(clientId);
        this.redirectUri = Objects.requireNonNull(redirectUri);
        this.http = HttpClient.newHttpClient();
    }

    // ======= Offentliga hjälpfunktioner för spelet =======

    /** Startar OAuth-flödet (öppnar webbläsaren), väntar på callback och byter code → tokens. */
    public void login() throws Exception {
        // 1) Generera PKCE-uppgifter
        String codeChallengeMethod = "S256";
        this.codeVerifier = randomUrlSafeString(64);
        String codeChallenge = base64UrlNoPad(sha256(codeVerifier.getBytes(StandardCharsets.UTF_8)));

        // 2) Starta lokal callback-server
        URI redirect = URI.create(redirectUri);
        int port = redirect.getPort();
        if (port == -1) throw new IllegalStateException("redirectUri måste ha port, t.ex. http://localhost:8888/callback");

        CountDownLatch latch = new CountDownLatch(1);
        final String[] codeHolder = new String[1];
        HttpServer server = HttpServer.create(new InetSocketAddress(port), 0);
        server.createContext(redirect.getPath(), (HttpExchange ex) -> {
            try {
                String query = ex.getRequestURI().getQuery();
                String code = parseQueryParam(query, "code");
                String error = parseQueryParam(query, "error");
                String html;
                if (error != null) {
                    html = "<html><body>Spotify login misslyckades: " + escapeHtml(error) + "</body></html>";
                } else if (code != null) {
                    codeHolder[0] = code;
                    html = "<html><body>Klart! Du kan stänga detta fönster och gå tillbaka till spelet.</body></html>";
                } else {
                    html = "<html><body>Ingen code mottagen.</body></html>";
                }
                byte[] bytes = html.getBytes(StandardCharsets.UTF_8);
                ex.getResponseHeaders().add("Content-Type", "text/html; charset=utf-8");
                ex.sendResponseHeaders(200, bytes.length);
                ex.getResponseBody().write(bytes);
            } finally {
                ex.close();
                latch.countDown();
            }
        });
        server.start();

        // 3) Öppna webbläsaren mot authorize-URL
        String url = AUTH_URL
                + "?response_type=code"
                + "&client_id=" + urlenc(clientId)
                + "&redirect_uri=" + urlenc(redirectUri)
                + "&scope=" + urlenc(SCOPES)
                + "&code_challenge_method=" + urlenc(codeChallengeMethod)
                + "&code_challenge=" + urlenc(codeChallenge);
        if (Desktop.isDesktopSupported()) {
            Desktop.getDesktop().browse(URI.create(url));
        } else {
            System.out.println("Öppna i webbläsare: " + url);
        }

        // 4) Vänta på callback
        latch.await();
        server.stop(0);

        String code = codeHolder[0];
        if (code == null) {
            throw new IllegalStateException("Ingen auth code mottagen (avbrutet eller fel i redirect?).");
        }

        // 5) Exchange code → token
        exchangeCodeForTokens(code);
    }

    /** Spela upp en URI (t.ex. "spotify:track:...") på aktiv enhet (deviceId=null) eller specifik enhet. */
    public void playUri(String spotifyUri, String deviceId) throws Exception {
        ensureValidAccessToken();
        String url = API + "/me/player/play" + (deviceId != null ? "?device_id=" + urlenc(deviceId) : "");
        String body = "{\"uris\":[\"" + escapeJson(spotifyUri) + "\"]}";
        HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                .header("Authorization", "Bearer " + accessToken)
                .header("Content-Type", "application/json")
                .PUT(HttpRequest.BodyPublishers.ofString(body))
                .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() == 204) return;
        if (resp.statusCode() == 404) {
            throw new IllegalStateException("Ingen aktiv enhet. Öppna Spotify på en enhet först.");
        }
        if (resp.statusCode() == 403) {
            throw new IllegalStateException("Åtgärd nekad (kräver ofta Premium). Status 403.");
        }
        throw new IllegalStateException("Play misslyckades. Status " + resp.statusCode() + ": " + resp.body());
    }

    /** Pausa uppspelning. */
    public void pause() throws Exception {
        ensureValidAccessToken();
        String url = API + "/me/player/pause";
        HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                .header("Authorization", "Bearer " + accessToken)
                .PUT(HttpRequest.BodyPublishers.noBody())
                .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() == 204) return;
        throw new IllegalStateException("Pause misslyckades. Status " + resp.statusCode() + ": " + resp.body());
    }

    /** Nästa låt. */
    public void nextTrack() throws Exception {
        ensureValidAccessToken();
        String url = API + "/me/player/next";
        HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                .header("Authorization", "Bearer " + accessToken)
                .POST(HttpRequest.BodyPublishers.noBody())
                .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() == 204) return;
        throw new IllegalStateException("Next misslyckades. Status " + resp.statusCode() + ": " + resp.body());
    }

    /** Föregående låt. */
    public void previousTrack() throws Exception {
        ensureValidAccessToken();
        String url = API + "/me/player/previous";
        HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                .header("Authorization", "Bearer " + accessToken)
                .POST(HttpRequest.BodyPublishers.noBody())
                .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() == 204) return;
        throw new IllegalStateException("Previous misslyckades. Status " + resp.statusCode() + ": " + resp.body());
    }

    /** Lista enheter som Spotify kan spela på (returnerar rå JSON-sträng). */
    public String listDevices() throws Exception {
        ensureValidAccessToken();
        String url = API + "/me/player/devices";
        HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                .header("Authorization", "Bearer " + accessToken)
                .GET().build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() == 200) return resp.body();
        throw new IllegalStateException("Hämtning av devices misslyckades. Status " + resp.statusCode() + ": " + resp.body());
    }

    /** Transfer playback till en viss deviceId. */
    public void transferTo(String deviceId, boolean play) throws Exception {
        ensureValidAccessToken();
        String url = API + "/me/player";
        String body = "{\"device_ids\":[\"" + escapeJson(deviceId) + "\"],\"play\":" + (play ? "true" : "false") + "}";
        HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                .header("Authorization", "Bearer " + accessToken)
                .header("Content-Type", "application/json")
                .PUT(HttpRequest.BodyPublishers.ofString(body))
                .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() == 204) return;
        throw new IllegalStateException("Transfer misslyckades. Status " + resp.statusCode() + ": " + resp.body());
    }

    // ======= Tokenhantering =======

    private void ensureValidAccessToken() throws Exception {
        if (accessToken == null) {
            throw new IllegalStateException("Inte inloggad. Kör login() först.");
        }
        // förnya token lite innan expiry
        if (Instant.now().isAfter(accessTokenExpiry.minusSeconds(30))) {
            refreshAccessToken();
        }
    }

    private void exchangeCodeForTokens(String code) throws Exception {
        String data = "grant_type=authorization_code"
                + "&client_id=" + urlenc(clientId)
                + "&code=" + urlenc(code)
                + "&redirect_uri=" + urlenc(redirectUri)
                + "&code_verifier=" + urlenc(codeVerifier);

        HttpRequest req = HttpRequest.newBuilder(URI.create(TOKEN_URL))
                .header("Content-Type", "application/x-www-form-urlencoded")
                .POST(HttpRequest.BodyPublishers.ofString(data))
                .build();

        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("Token-förfrågan misslyckades. Status " + resp.statusCode() + ": " + resp.body());
        }
        parseAndStoreTokens(resp.body());
    }

    private void refreshAccessToken() throws Exception {
        if (refreshToken == null) throw new IllegalStateException("Saknar refresh token. Logga in igen.");
        String data = "grant_type=refresh_token"
                + "&client_id=" + urlenc(clientId)
                + "&refresh_token=" + urlenc(refreshToken);

        HttpRequest req = HttpRequest.newBuilder(URI.create(TOKEN_URL))
                .header("Content-Type", "application/x-www-form-urlencoded")
                .POST(HttpRequest.BodyPublishers.ofString(data))
                .build();

        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("Refresh misslyckades. Status " + resp.statusCode() + ": " + resp.body());
        }
        parseAndStoreTokens(resp.body());
    }

    // Minimal JSON-parsning (utan externa libbar) – plockar ut enkla fält.
    private void parseAndStoreTokens(String json) {
        String at = jsonPick(json, "access_token");
        String rt = jsonPick(json, "refresh_token"); // kan vara null vid vissa refresh-responser
        String exp = jsonPickNumber(json, "expires_in");

        if (at == null) throw new IllegalStateException("access_token saknas i svaret: " + json);
        this.accessToken = at;
        if (rt != null && !rt.isEmpty()) {
            this.refreshToken = rt;
        }
        long expiresIn = 3600;
        if (exp != null) {
            try { expiresIn = Long.parseLong(exp); } catch (NumberFormatException ignore) {}
        }
        this.accessTokenExpiry = Instant.now().plusSeconds(expiresIn);
    }

    // ======= Hjälpmetoder =======

    private static String urlenc(String s) {
        return URLEncoder.encode(s, StandardCharsets.UTF_8);
    }

    private static String randomUrlSafeString(int len) {
        byte[] bytes = new byte[len];
        new SecureRandom().nextBytes(bytes);
        return base64UrlNoPad(bytes);
    }

    private static byte[] sha256(byte[] input) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return md.digest(input);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    private static String base64UrlNoPad(byte[] bytes) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private static String parseQueryParam(String query, String key) {
        if (query == null) return null;
        String[] parts = query.split("&");
        for (String p : parts) {
            int i = p.indexOf('=');
            if (i > 0) {
                String k = decode(p.substring(0, i));
                String v = decode(p.substring(i + 1));
                if (key.equals(k)) return v;
            }
        }
        return null;
    }

    private static String decode(String s) {
        return java.net.URLDecoder.decode(s, StandardCharsets.UTF_8);
    }

    private static String escapeHtml(String s) {
        return s == null ? "" : s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
    }

    private static String escapeJson(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    // Minimal och naiv JSON-fälthämtning: letar efter "key":"value"
    private static String jsonPick(String json, String key) {
        String needle = "\"" + key + "\"";
        int i = json.indexOf(needle);
        if (i < 0) return null;
        int colon = json.indexOf(':', i + needle.length());
        if (colon < 0) return null;
        // hoppa whitespace
        int j = colon + 1;
        while (j < json.length() && Character.isWhitespace(json.charAt(j))) j++;
        if (j >= json.length()) return null;

        char c = json.charAt(j);
        if (c == '"') {
            // sträng
            int start = j + 1;
            StringBuilder sb = new StringBuilder();
            for (int k = start; k < json.length(); k++) {
                char ch = json.charAt(k);
                if (ch == '\\') {
                    if (k + 1 < json.length()) {
                        char e = json.charAt(++k);
                        if (e == '"' || e == '\\' || e == '/') sb.append(e);
                        else if (e == 'b') sb.append('\b');
                        else if (e == 'f') sb.append('\f');
                        else if (e == 'n') sb.append('\n');
                        else if (e == 'r') sb.append('\r');
                        else if (e == 't') sb.append('\t');
                        else sb.append(e); // enkel fallback
                    }
                } else if (ch == '"') {
                    return sb.toString();
                } else {
                    sb.append(ch);
                }
            }
            return null;
        } else {
            // nummer/bool/null: läs tills komma eller }.
            int end = j;
            while (end < json.length()) {
                char ch = json.charAt(end);
                if (ch == ',' || ch == '}' || ch == ']') break;
                end++;
            }
            return json.substring(j, end).trim().replace("\"", "");
        }
    }

    private static String jsonPickNumber(String json, String key) {
        String v = jsonPick(json, key);
        if (v == null) return null;
        // rensa ev. citattecken (om svaret skulle vara sträng)
        return v.replaceAll("[^0-9]", "");
    }

    // ======= Enkel manuell test i konsol =======
    public static void main(String[] args) throws Exception {
        String clientId = "<DIN_CLIENT_ID_HÄR>";
        String redirect = "http://localhost:8888/callback";

        SpotifyConnector sp = new SpotifyConnector(clientId, redirect);

        System.out.println("Startar login-flöde...");
        sp.login();
        System.out.println("Inloggad!");

        // Visa enheter
        String devices = sp.listDevices();
        System.out.println("Devices JSON: " + devices);

        // Spela en låt på aktiv enhet (byt ut TRACK_ID)
        // sp.playUri("spotify:track:4uLU6hMCjMI75M1A2tKUQC", null);

        // Pausa/Next/Prev exempel:
        // sp.pause();
        // sp.nextTrack();
        // sp.previousTrack();

        System.out.println("Klar.");
    }
}
