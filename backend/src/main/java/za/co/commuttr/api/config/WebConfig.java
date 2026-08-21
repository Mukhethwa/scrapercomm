package za.co.commuttr.api.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.Resource;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.ViewControllerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;
import org.springframework.web.servlet.resource.PathResourceResolver;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * CORS and static hosting, reproducing what the FastAPI app did:
 *
 * <ul>
 *   <li>{@code CORSMiddleware(allow_origins=["*"], allow_methods=["GET"])} so the Vite
 *       dev server on :5173 can call the API directly during development;</li>
 *   <li>{@code app.mount("/", StaticFiles(directory=web/dist, html=True))} when a built
 *       UI is present, registered so that {@code /api/**} still wins.</li>
 * </ul>
 *
 * <p>The React app itself needs no change: its dev proxy already points at :8000, which
 * is the port this service listens on.
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {

    private static final Logger log = LoggerFactory.getLogger(WebConfig.class);

    private final String[] allowedOriginPatterns;
    private final String[] allowedMethods;
    private final Path webDist;

    public WebConfig(@Value("${commuttr.cors.allowed-origin-patterns}") String[] allowedOriginPatterns,
                     @Value("${commuttr.cors.allowed-methods}") String[] allowedMethods,
                     @Value("${commuttr.web-dist}") String webDist) {
        this.allowedOriginPatterns = allowedOriginPatterns;
        this.allowedMethods = allowedMethods;
        this.webDist = Path.of(webDist).toAbsolutePath().normalize();
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/**")
                // allowedOriginPatterns rather than allowedOrigins: "*" stays legal even
                // if credentials are ever switched on.
                .allowedOriginPatterns(allowedOriginPatterns)
                .allowedMethods(allowedMethods)
                .allowedHeaders("*")
                .maxAge(3600);
    }

    /**
     * Serve index.html for "/" itself.
     *
     * <p>The resource handler below covers every other path, but Spring's
     * {@code ResourceHttpRequestHandler} rejects an empty resource path before any
     * resolver sees it, so the bare root would 404 while {@code /index.html} worked.
     * FastAPI's {@code StaticFiles(..., html=True)} served the root, so this restores it.
     */
    @Override
    public void addViewControllers(ViewControllerRegistry registry) {
        if (Files.isDirectory(webDist)) {
            registry.addViewController("/").setViewName("forward:/index.html");
        }
    }

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        if (!Files.isDirectory(webDist)) {
            log.info("No built UI at {} — serving the API only (run 'npm run build' in web/ to bundle it)",
                    webDist);
            return;
        }
        log.info("Serving the built React UI from {}", webDist);

        registry.addResourceHandler("/**")
                .addResourceLocations(webDist.toUri().toString())
                .resourceChain(true)
                .addResolver(new PathResourceResolver() {
                    @Override
                    protected Resource getResource(String resourcePath, Resource location)
                            throws IOException {
                        Resource requested = super.getResource(resourcePath, location);
                        if (requested != null) {
                            return requested;
                        }
                        // StaticFiles(html=True) served index.html for directory requests
                        // and 404-ed everything else. Same rule here.
                        boolean directoryRequest = resourcePath.isEmpty() || resourcePath.endsWith("/");
                        return directoryRequest ? super.getResource("index.html", location) : null;
                    }
                });
    }
}
