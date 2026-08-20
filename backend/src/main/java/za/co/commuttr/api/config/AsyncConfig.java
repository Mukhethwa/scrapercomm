package za.co.commuttr.api.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.aop.interceptor.AsyncUncaughtExceptionHandler;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.AsyncConfigurer;
import org.springframework.scheduling.annotation.EnableAsync;

import java.lang.reflect.Method;
import java.util.Arrays;

/**
 * Turns on {@code @Async}, which the search-analytics listener uses to keep its
 * PostgreSQL INSERT off the request thread.
 *
 * <p>{@code getAsyncExecutor()} is deliberately left at its default so Spring Boot's
 * {@code applicationTaskExecutor} is used. With
 * {@code spring.threads.virtual.enabled=true} that executor is a
 * {@code SimpleAsyncTaskExecutor} backed by virtual threads, so every analytics write
 * gets its own cheap carrier-free thread instead of contending for a bounded pool.
 */
@Configuration
@EnableAsync
public class AsyncConfig implements AsyncConfigurer {

    private static final Logger log = LoggerFactory.getLogger(AsyncConfig.class);

    /**
     * A void {@code @Async} method's exception would otherwise vanish. Analytics is
     * best-effort, so log it and carry on.
     */
    @Override
    public AsyncUncaughtExceptionHandler getAsyncUncaughtExceptionHandler() {
        return (Throwable ex, Method method, Object... params) ->
                log.error("Async {} failed with params {}", method.getName(), Arrays.toString(params), ex);
    }
}
