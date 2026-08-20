package za.co.commuttr.api.web;

import org.springframework.http.HttpStatus;

/**
 * The Java equivalent of FastAPI's {@code HTTPException(status, "message")}. Rendered by
 * {@link ApiExceptionHandler} as {@code {"detail": "message"}} with the same status.
 */
public class ApiException extends RuntimeException {

    private final HttpStatus status;

    public ApiException(HttpStatus status, String detail) {
        super(detail);
        this.status = status;
    }

    public HttpStatus getStatus() {
        return status;
    }

    public static ApiException notFound(String detail) {
        return new ApiException(HttpStatus.NOT_FOUND, detail);
    }

    public static ApiException badRequest(String detail) {
        return new ApiException(HttpStatus.BAD_REQUEST, detail);
    }
}
