/** API errors in the standard envelope `{error: {code, message, details?}}` (plan §9.1). */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }

  toBody(): { error: { code: string; message: string; details?: unknown } } {
    return {
      error: {
        code: this.code,
        message: this.message,
        ...(this.details === undefined ? {} : { details: this.details }),
      },
    };
  }
}

export const badRequest = (message: string, details?: unknown): ApiError =>
  new ApiError(400, "bad_request", message, details);

export const notFoundError = (message = "Not found"): ApiError =>
  new ApiError(404, "not_found", message);

export const internalError = (): ApiError => new ApiError(500, "internal", "Internal server error");
