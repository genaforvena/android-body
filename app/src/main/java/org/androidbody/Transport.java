// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import android.os.Build;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.Socket;
import java.net.URL;
import java.security.GeneralSecurityException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;

final class Transport {
    private final String endpoint;
    private final String secret;
    private volatile boolean cancelled;
    private volatile HttpURLConnection current;
    Transport(String endpoint, String secret, boolean allowHttp) {
        this.endpoint = Protocol.endpoint(endpoint, allowHttp);
        this.secret = Protocol.secret(secret);
    }
    String getActions(long after) throws IOException { return request("GET", "/actions?after=" + after, null); }
    void postObservations(String body) throws IOException {
        String response = request("POST", "/observations", body);
        int count = 0;
        for (int i = 0; i < body.length(); i++) if (body.charAt(i) == '\n') count++;
        try { Protocol.acknowledgment(response, count); }
        catch (IllegalArgumentException e) { throw new ProtocolFailure("Invalid observation acknowledgment"); }
    }
    void cancel() {
        cancelled = true;
        HttpURLConnection connection = current;
        if (connection != null) connection.disconnect();
    }
    private String request(String method, String path, String body) throws IOException {
        if (cancelled) throw new IOException("Stopped");
        HttpURLConnection connection = (HttpURLConnection) new URL(endpoint + path).openConnection();
        current = connection;
        try {
            if (cancelled) throw new IOException("Stopped");
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(8000);
            connection.setInstanceFollowRedirects(false); // Never forward a credential to a redirect target.
            connection.setUseCaches(false);
            connection.setRequestMethod(method);
            connection.setRequestProperty("Authorization", "Bearer " + secret);
            connection.setRequestProperty("Accept", "text/plain");
            connection.setRequestProperty("Accept-Encoding", "identity");
            if (connection instanceof HttpsURLConnection && Build.VERSION.SDK_INT < 22) {
                try {
                    SSLContext context = SSLContext.getInstance("TLS");
                    context.init(null, null, null);
                    ((HttpsURLConnection) connection).setSSLSocketFactory(new LegacyTls(context.getSocketFactory()));
                } catch (GeneralSecurityException e) { throw new IOException("TLS initialization failed", e); }
            }
            if (body != null) {
                byte[] bytes = body.getBytes(Protocol.UTF8);
                if (bytes.length > Protocol.MAX_BODY_BYTES) throw new IOException("Observation batch too large");
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "text/plain; charset=utf-8");
                connection.setFixedLengthStreamingMode(bytes.length);
                OutputStream stream = connection.getOutputStream();
                try { stream.write(bytes); } finally { stream.close(); }
            }
            int status = connection.getResponseCode();
            if (!("GET".equals(method) ? status == 200 : status == 201)) throw new HttpFailure(status);
            String type = connection.getContentType();
            if (type == null || !type.toLowerCase(Locale.US).split(";", 2)[0].trim().equals("text/plain")) {
                throw new ProtocolFailure("Expected text/plain response");
            }
            String encoding = connection.getContentEncoding();
            if (encoding != null && !"identity".equalsIgnoreCase(encoding)) throw new ProtocolFailure("Unexpected content encoding");
            if (connection.getContentLength() > Protocol.MAX_BODY_BYTES) throw new ProtocolFailure("Response too large");
            InputStream stream = connection.getInputStream();
            try {
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                byte[] buffer = new byte[2048];
                int count;
                while ((count = stream.read(buffer)) != -1) {
                    if (cancelled) throw new IOException("Stopped");
                    if (bytes.size() + count > Protocol.MAX_BODY_BYTES) throw new ProtocolFailure("Response too large");
                    bytes.write(buffer, 0, count);
                }
                try { return Protocol.decode(bytes.toByteArray()); }
                catch (IllegalArgumentException e) { throw new ProtocolFailure("Invalid UTF-8 response"); }
            } finally { stream.close(); }
        } finally {
            connection.disconnect();
            current = null;
        }
    }
    static final class HttpFailure extends IOException {
        final int status;
        HttpFailure(int status) { super("HTTP " + status); this.status = status; }
        boolean fatal() { return status < 500 && status != 408 && status != 429 || status == 507; }
    }
    static final class ProtocolFailure extends IOException { ProtocolFailure(String message) { super(message); } }

    /** API19–21 TLS1.2 opt-in only. Trust managers and hostname verification stay intact. */
    private static final class LegacyTls extends SSLSocketFactory {
        private final SSLSocketFactory delegate;
        LegacyTls(SSLSocketFactory delegate) { this.delegate = delegate; }
        private Socket configure(Socket socket) {
            if (socket instanceof SSLSocket) {
                SSLSocket ssl = (SSLSocket) socket;
                List<String> protocols = new ArrayList<String>();
                for (String protocol : ssl.getSupportedProtocols()) {
                    if ("TLSv1.2".equals(protocol) || "TLSv1.3".equals(protocol)) protocols.add(protocol);
                }
                if (protocols.isEmpty()) throw new IllegalStateException("TLS1.2 unavailable");
                ssl.setEnabledProtocols(protocols.toArray(new String[protocols.size()]));
            }
            return socket;
        }
        @Override public String[] getDefaultCipherSuites() { return delegate.getDefaultCipherSuites(); }
        @Override public String[] getSupportedCipherSuites() { return delegate.getSupportedCipherSuites(); }
        @Override public Socket createSocket() throws IOException { return configure(delegate.createSocket()); }
        @Override public Socket createSocket(Socket s, String h, int p, boolean c) throws IOException { return configure(delegate.createSocket(s, h, p, c)); }
        @Override public Socket createSocket(String h, int p) throws IOException { return configure(delegate.createSocket(h, p)); }
        @Override public Socket createSocket(String h, int p, InetAddress l, int lp) throws IOException { return configure(delegate.createSocket(h, p, l, lp)); }
        @Override public Socket createSocket(InetAddress h, int p) throws IOException { return configure(delegate.createSocket(h, p)); }
        @Override public Socket createSocket(InetAddress h, int p, InetAddress l, int lp) throws IOException { return configure(delegate.createSocket(h, p, l, lp)); }
    }
}
