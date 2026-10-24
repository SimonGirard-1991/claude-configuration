package probe.app;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.context.request.WebRequest;

@RestController
public class DocumentController {

    static final long VERSION = 7;

    @GetMapping("/doc")
    public ResponseEntity<String> get() {
        return ResponseEntity.ok().eTag(Long.toString(VERSION)).body("doc");
    }

    @PutMapping("/doc")
    public ResponseEntity<String> put(WebRequest request, @RequestBody String body) {
        if (request.checkNotModified(Long.toString(VERSION))) {
            return null;
        }
        return ResponseEntity.ok("updated");
    }
}
