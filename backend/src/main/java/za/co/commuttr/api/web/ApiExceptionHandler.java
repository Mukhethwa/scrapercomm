package za.co.commuttr.api.web;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.web.ErrorResponse;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.util.List;
import java.util.Map;

/**
 * Reproduces FastAPI's error envelope so the React client sees identical bodies:
 *
 * <ul>
 *   <li>{@code HTTPException} -> the given status with {@code {"detail": "message"}}</li>
 *   <li>a missing or unparseable query parameter -> 422 with a {@code detail} array
 *       (Spring's own default would be 400, which would change the contract)</li>
 *   <li>an unknown path -> 404 with {@code {"detail": "Not Found"}}</li>
 * </ul>
 */
@RestControllerAdvice
public class ApiExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(ApiExceptionHandler.class);

    /** One entry of FastAPI's 422 detail array. */
    public record ValidationDetail(String type, List<Object> loc, String msg, Object input) { }

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<Map<String, Object>> handleApiException(ApiException ex) {
        return ResponseEntity.status(ex.getStatus()).body(Map.of("detail", ex.getMessage()));
    }

    @ExceptionHandler(MissingServletRequestParameterException.class)
    public ResponseEntity<Map<String, Object>> handleMissingParam(MissingServletRequestParameterException ex) {
        ValidationDetail detail = new ValidationDetail(
                "missing",
                List.of("query", ex.getParameterName()),
                "Field required",
                null);
        return unprocessable(detail);
    }

    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<Map<String, Object>> handleTypeMismatch(MethodArgumentTypeMismatchException ex) {
        Class<?> required = ex.getRequiredType();
        boolean wantsInt = required == Integer.class || required == int.class;
        ValidationDetail detail = new ValidationDetail(
                wantsInt ? "int_parsing" : "float_parsing",
                List.of("query", ex.getName()),
                wantsInt
                        ? "Input should be a valid integer, unable to parse string as an integer"
                        : "Input should be a valid number, unable to parse string as a number",
                ex.getValue());
        return unprocessable(detail);
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<Map<String, Object>> handleNoResource(NoResourceFoundException ex) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("detail", "Not Found"));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> handleUnexpected(Exception ex) {
        // Spring's own MVC exceptions (405 method not allowed, 406 not acceptable, ...)
        // implement ErrorResponse and already carry the right status — keep it, and only
        // reshape the body into FastAPI's envelope.
        if (ex instanceof ErrorResponse errorResponse) {
            HttpStatusCode status = errorResponse.getStatusCode();
            return ResponseEntity.status(status).body(Map.of("detail", reasonFor(status)));
        }
        log.error("Unhandled error serving request", ex);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(Map.of("detail", "Internal Server Error"));
    }

    /** "Method Not Allowed" rather than "METHOD_NOT_ALLOWED", as Starlette phrased it. */
    private static String reasonFor(HttpStatusCode status) {
        HttpStatus resolved = HttpStatus.resolve(status.value());
        return resolved == null ? String.valueOf(status.value()) : resolved.getReasonPhrase();
    }

    private ResponseEntity<Map<String, Object>> unprocessable(ValidationDetail detail) {
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY)
                .body(Map.of("detail", List.of(detail)));
    }
}
