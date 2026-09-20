
package com.example.collegedigitalwallet

object UserSession {
    var username: String? = null
    var studentId: String? = null
    var program: String? = null
    var fullName: String? = null

    var balance: Double? = null

    fun clear() {
        username = null
        studentId = null
        program = null
        balance = null
        fullName = null
    }
}
