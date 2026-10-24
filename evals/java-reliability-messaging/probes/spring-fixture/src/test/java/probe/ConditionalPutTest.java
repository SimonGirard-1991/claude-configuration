package probe;

import static probe.Facts.fact;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.SpringBootTest.WebEnvironment;
import org.springframework.boot.test.web.server.LocalServerPort;
import probe.app.ProbeApplication;

@SpringBootTest(classes = ProbeApplication.class, webEnvironment = WebEnvironment.RANDOM_PORT)
class ConditionalPutTest {

    @LocalServerPort int port;
    private final HttpClient client = HttpClient.newHttpClient();

    @Test
    void checkNotModifiedOnPut() throws Exception {
        var get = client.send(HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/doc")).build(),
                HttpResponse.BodyHandlers.ofString());
        fact("etag-header", "ResponseEntity.eTag(\"7\") sends ETag: " + get.headers().firstValue("ETag").orElse("none"));
        for (String ifMatch : new String[] {null, "\"7\"", "\"6\"", "W/\"7\"", "*", "\"6\", \"7\""}) {
            var builder = HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/doc"))
                    .PUT(HttpRequest.BodyPublishers.ofString("x"))
                    .header("Content-Type", "text/plain");
            if (ifMatch != null) {
                builder.header("If-Match", ifMatch);
            }
            var response = client.send(builder.build(), HttpResponse.BodyHandlers.ofString());
            fact("checkNotModified-put If-Match=" + (ifMatch == null ? "absent" : ifMatch),
                    response.statusCode() + " " + response.body());
        }
    }
}
